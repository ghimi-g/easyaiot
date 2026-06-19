"""
SRS/ZLM DVR 路径解析、文件稳定检测与封面抽取工具。
"""
import logging
import os
import subprocess
import time
from datetime import datetime as dt, timezone as _tz, timedelta as _td
from typing import Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# SRS DVR 文件名中的 [timestamp] 是 Unix 纪元毫秒（UTC 基准）。当容器时钟实际为 UTC
# （例如 TZ=Asia/Shanghai 但缺 tzdata，fromtimestamp 退化为 UTC 墙钟）时，必须显式按
# 上海时区换算为本地墙钟时间，才能与按 +08 存储的告警 time 对齐匹配 record_path。
_SHANGHAI_TZ = _tz(_td(hours=8))


def srs_dvr_min_file_bytes() -> int:
    try:
        return max(512, int((os.getenv('SRS_DVR_MIN_FILE_BYTES') or '8192').strip()))
    except Exception:
        return 8192


def parse_srs_dvr_segment_start_from_filename(absolute_file_path: str):
    filename = os.path.basename(absolute_file_path)
    stem, ext = os.path.splitext(filename)
    if ext.lower() != '.flv' or not stem.isdigit():
        return None
    try:
        ts = int(stem)
        epoch_seconds = ts / 1000.0 if ts > 10**12 else float(ts)
        # 以上海时区解释纪元秒，再去掉 tzinfo 得到本地墙钟（21:xx 而非容器 UTC 的 13:xx）
        return dt.fromtimestamp(epoch_seconds, tz=_SHANGHAI_TZ).replace(tzinfo=None)
    except (ValueError, OSError):
        return None


def parse_srs_dvr_path_date(absolute_file_path: str) -> Tuple[Optional[str], Optional[dt]]:
    segment_start = parse_srs_dvr_segment_start_from_filename(absolute_file_path)
    parts = [p for p in absolute_file_path.replace('\\', '/').split('/') if p]
    try:
        if 'playbacks' not in parts:
            return None, None
        i = parts.index('playbacks')
        if len(parts) < i + 7:
            return None, None
        y, mo, d = parts[i + 3], parts[i + 4], parts[i + 5]
        if len(y) != 4 or not y.isdigit() or not mo.isdigit() or not d.isdigit():
            return None, None
        date_dir = f'{y}/{mo}/{d}'
        if segment_start is not None:
            return date_dir, segment_start
        try:
            record_time = dt.fromtimestamp(os.path.getmtime(absolute_file_path))
        except OSError:
            record_time = dt(int(y), int(mo), int(d))
        return date_dir, record_time
    except (ValueError, IndexError, OSError):
        return None, None


def wait_dvr_file_stable(
    absolute_file_path: str,
    max_retries: int = 12,
    retry_interval: float = 1.0,
    stable_checks: int = 3,
) -> int:
    """等待 DVR 文件大小连续 stable_checks 次采样不变。"""
    min_bytes = srs_dvr_min_file_bytes()
    last_size = -1
    stable_count = 0
    for attempt in range(max_retries):
        if not os.path.exists(absolute_file_path):
            stable_count = 0
            time.sleep(retry_interval)
            continue
        try:
            size = os.path.getsize(absolute_file_path)
        except OSError:
            stable_count = 0
            time.sleep(retry_interval)
            continue
        if size == last_size and size >= min_bytes:
            stable_count += 1
            if stable_count >= stable_checks:
                return size
        else:
            stable_count = 1 if size >= min_bytes else 0
        last_size = size
        time.sleep(retry_interval)
    return 0


def resolve_playback_absolute_path(local_path: str, cwd: str = '') -> str:
    """规范化 Hook 中的录像路径（容器 /data → 宿主机 CephFS 挂载）。"""
    if not local_path:
        return local_path
    if not os.path.isabs(local_path) and cwd:
        local_path = os.path.join(cwd, local_path)

    try:
        from cluster_storage import resolve_container_path
        mapped = resolve_container_path(local_path, cwd='')
        if mapped != local_path:
            return mapped
    except ImportError:
        media_root = (os.getenv('MEDIA_HOST_DATA_ROOT') or os.getenv('SRS_HOST_DATA_ROOT') or '').strip()
        if media_root:
            media_root = os.path.normpath(os.path.expanduser(os.path.expandvars(media_root)))
            for prefix in ('/data', '/mnt/easyaiot-media'):
                p = os.path.normpath(local_path)
                if p == prefix or p.startswith(prefix + os.sep):
                    if not os.path.lexists(p):
                        try:
                            rel = os.path.relpath(p, prefix)
                            mapped = os.path.join(media_root, rel)
                            if os.path.lexists(mapped) or prefix == '/data':
                                return mapped
                        except ValueError:
                            pass

    container_root = (os.getenv('SRS_CONTAINER_DATA_ROOT') or '/data').rstrip('/\\')
    try:
        p = os.path.normpath(local_path)
    except Exception:
        return local_path
    if not (p == container_root or p.startswith(container_root + os.sep)):
        return local_path
    if os.path.lexists(p):
        return local_path
    host_root = (os.getenv('SRS_HOST_DATA_ROOT') or '/data').strip()
    host_root = os.path.normpath(os.path.expanduser(os.path.expandvars(host_root)))
    try:
        rel = os.path.relpath(p, container_root)
    except ValueError:
        return local_path
    return os.path.join(host_root, rel)


def ffprobe_video_duration_seconds(video_path: str) -> float:
    try:
        result = subprocess.run(
            [
                'ffprobe', '-v', 'error', '-select_streams', 'v:0',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path,
            ],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return max(0.0, float(result.stdout.strip()))
    except Exception:
        pass
    return 0.0


def extract_thumbnail_from_video(video_path, output_path=None, frame_position=0.1):
    try:
        if not os.path.exists(video_path) or not os.access(video_path, os.R_OK):
            return None if output_path is None else False
        file_size = os.path.getsize(video_path)
        if file_size < srs_dvr_min_file_bytes():
            return None if output_path is None else False
        abs_video_path = os.path.abspath(video_path)
        frame = _extract_thumbnail_ffmpeg(abs_video_path, frame_position)
        if frame is None:
            frame = _extract_thumbnail_opencv(abs_video_path, frame_position)
        if frame is None:
            return None if output_path is None else False
        if output_path:
            cv2.imwrite(output_path, frame)
            return True
        return frame
    except Exception as e:
        logger.error('抽取视频封面失败: %s, error=%s', video_path, e, exc_info=True)
        return None if output_path is None else False


def _extract_thumbnail_ffmpeg(video_path: str, frame_position: float = 0.1) -> Optional[np.ndarray]:
    duration = ffprobe_video_duration_seconds(video_path)
    seek_sec = max(0.0, duration * frame_position) if duration > 0 else 0.0
    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-ss', str(seek_sec),
        '-i', video_path, '-map', '0:v:0', '-frames:v', '1', '-q:v', '2',
        '-f', 'image2pipe', '-vcodec', 'mjpeg', 'pipe:1',
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode != 0 or not result.stdout:
            return None
        return cv2.imdecode(np.frombuffer(result.stdout, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None


def _extract_thumbnail_opencv(video_path: str, frame_position: float = 0.1) -> Optional[np.ndarray]:
    cap = cv2.VideoCapture(os.path.abspath(video_path), cv2.CAP_FFMPEG)
    if not cap.isOpened():
        cap.release()
        return None
    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            ret, frame = cap.read()
            return frame if ret and frame is not None else None
        target_frame = max(1, int(total_frames * frame_position))
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()
        return frame if ret and frame is not None else None
    finally:
        cap.release()
