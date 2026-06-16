"""SAM 3.1 模型权重下载与状态查询（默认从魔塔 ModelScope 拉取 facebook/sam3.1）"""
import os
import re
import shutil
import threading
import urllib.error
import urllib.request
from typing import Any, Dict

from app.services.sam_service import SAM_MODEL_PATH

SAM_MODEL_DOWNLOAD_URL = os.getenv('SAM_MODEL_DOWNLOAD_URL', '').strip()
SAM_MODELSCOPE_ID = os.getenv('SAM_MODELSCOPE_ID', 'facebook/sam3.1').strip()
SAM_MODELSCOPE_FILE = os.getenv('SAM_MODELSCOPE_FILE', 'sam3.1_multiplex.pt').strip()
SAM_MODELSCOPE_REVISION = os.getenv('SAM_MODELSCOPE_REVISION', 'master').strip()
# facebook/sam3.1 权重约 3.26 GB
ESTIMATED_MODEL_SIZE_BYTES = int(os.getenv('SAM_MODEL_ESTIMATED_BYTES', str(3502755717)))
MIN_MODEL_SIZE_BYTES = 100 * 1024 * 1024
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
DOWNLOAD_USER_AGENT = 'EasyAIoT-AI/1.0'
DOWNLOAD_TIMEOUT_SEC = int(os.getenv('SAM_MODEL_DOWNLOAD_TIMEOUT', '300'))

_lock = threading.Lock()
_state: Dict[str, Any] = {
    'status': 'idle',
    'stage': 'idle',
    'progress': 0,
    'downloaded_bytes': 0,
    'total_bytes': 0,
    'error': None,
}


def _partial_path() -> str:
    return f'{SAM_MODEL_PATH}.downloading'


def _modelscope_staging_dir() -> str:
    return os.path.join(os.path.dirname(SAM_MODEL_PATH) or '.', '.modelscope_staging')


def _modelscope_staging_file() -> str:
    return os.path.join(_modelscope_staging_dir(), SAM_MODELSCOPE_FILE)


def _download_source() -> str:
    if SAM_MODEL_DOWNLOAD_URL:
        return 'http'
    return 'modelscope'


def _can_auto_download() -> bool:
    if SAM_MODEL_DOWNLOAD_URL:
        return True
    return bool(SAM_MODELSCOPE_ID and SAM_MODELSCOPE_FILE)


def _get_partial_bytes() -> int:
    candidates = [_partial_path(), _modelscope_staging_file()]
    best = 0
    for path in candidates:
        if not os.path.isfile(path):
            continue
        try:
            best = max(best, os.path.getsize(path))
        except OSError:
            continue
    return best


def _parse_content_range_total(content_range: str, content_length: int, existing_size: int) -> int:
    if content_range:
        match = re.match(r'bytes\s+\d+-\d+/(\d+|\*)', content_range.strip(), re.I)
        if match and match.group(1) != '*':
            return int(match.group(1))
    if content_length > 0:
        return existing_size + content_length
    return ESTIMATED_MODEL_SIZE_BYTES


def _calc_progress(downloaded: int, total: int) -> int:
    if total <= 0:
        return 0
    return min(95, int(downloaded * 95 / total))


def _reset_error_if_idle() -> None:
    if _state['status'] == 'idle':
        _state['error'] = None


def is_sam_model_available() -> bool:
    if not os.path.isfile(SAM_MODEL_PATH):
        return False
    try:
        return os.path.getsize(SAM_MODEL_PATH) >= MIN_MODEL_SIZE_BYTES
    except OSError:
        return False


def _sync_partial_progress_locked() -> None:
    if is_sam_model_available():
        return
    partial_bytes = _get_partial_bytes()
    if partial_bytes <= 0:
        return
    total = int(_state['total_bytes']) or ESTIMATED_MODEL_SIZE_BYTES
    if _state['status'] != 'downloading':
        _state['downloaded_bytes'] = partial_bytes
        if partial_bytes < total:
            _state['progress'] = _calc_progress(partial_bytes, total)


def _build_status_locked() -> Dict[str, Any]:
    exists = is_sam_model_available()
    size_bytes = os.path.getsize(SAM_MODEL_PATH) if exists else 0
    partial_bytes = 0 if exists else _get_partial_bytes()
    resumable = partial_bytes > 0 and not exists and _can_auto_download()
    _reset_error_if_idle()
    downloading = _state['status'] == 'downloading'
    stage = _state['stage']
    if exists:
        stage = 'done'
    elif downloading:
        stage = _state['stage'] or 'downloading'
    elif resumable and _state['status'] == 'error':
        stage = 'error'
    elif resumable:
        stage = 'idle'

    total_bytes = int(_state['total_bytes']) or ESTIMATED_MODEL_SIZE_BYTES
    downloaded_bytes = int(_state['downloaded_bytes'])
    if not exists and partial_bytes > downloaded_bytes:
        downloaded_bytes = partial_bytes
    if not exists and partial_bytes > 0 and total_bytes <= 0:
        total_bytes = ESTIMATED_MODEL_SIZE_BYTES

    progress = 0
    if exists:
        progress = 100
    elif downloading or resumable:
        progress = _calc_progress(downloaded_bytes, total_bytes)

    return {
        'exists': exists,
        'filename': os.path.basename(SAM_MODEL_PATH),
        'path': SAM_MODEL_PATH,
        'size_bytes': size_bytes,
        'downloading': downloading,
        'resumable': resumable,
        'stage': stage,
        'progress': progress,
        'downloaded_bytes': downloaded_bytes,
        'total_bytes': total_bytes,
        'error': _state['error'],
        'source': _download_source(),
        'modelscope_id': SAM_MODELSCOPE_ID if _download_source() == 'modelscope' else None,
    }


def get_sam_model_status() -> Dict[str, Any]:
    with _lock:
        _sync_partial_progress_locked()
        return _build_status_locked()


def _set_progress(stage: str, progress: int, downloaded: int = 0, total: int = 0) -> None:
    with _lock:
        _state['stage'] = stage
        _state['downloaded_bytes'] = downloaded
        if total > 0:
            _state['total_bytes'] = total
        _state['progress'] = max(int(_state['progress']), int(progress))


def _finalize_partial(partial_path: str) -> None:
    size = os.path.getsize(partial_path)
    if size < MIN_MODEL_SIZE_BYTES:
        raise RuntimeError(f'下载文件过小（{size} bytes），可能不完整')
    _set_progress('installing', 96, downloaded=size, total=size)
    os.makedirs(os.path.dirname(SAM_MODEL_PATH) or '.', exist_ok=True)
    os.replace(partial_path, SAM_MODEL_PATH)


def _install_downloaded_file(src_path: str) -> None:
    if not os.path.isfile(src_path):
        raise RuntimeError(f'未找到已下载权重: {src_path}')
    partial_path = _partial_path()
    if os.path.abspath(src_path) != os.path.abspath(partial_path):
        shutil.copy2(src_path, partial_path)
    _finalize_partial(partial_path)


def _poll_staging_file(stop_event: threading.Event) -> None:
    """轮询 ModelScope 本地 staging 文件大小，作为进度回调的补充。"""
    staging_file = _modelscope_staging_file()
    while not stop_event.wait(1.0):
        if not os.path.isfile(staging_file):
            continue
        try:
            size = os.path.getsize(staging_file)
        except OSError:
            continue
        total = ESTIMATED_MODEL_SIZE_BYTES
        with _lock:
            if size > int(_state['downloaded_bytes']):
                _state['downloaded_bytes'] = size
                _state['total_bytes'] = total
                _state['progress'] = max(
                    int(_state['progress']),
                    _calc_progress(size, total),
                )


def _download_modelscope_with_progress() -> None:
    try:
        from modelscope.hub.snapshot_download import snapshot_download
        from modelscope.hub.callback import ProgressCallback
    except ImportError as exc:
        raise RuntimeError(
            '未安装 modelscope，无法从魔塔下载 SAM 3.1。'
            '请在 AI 服务环境执行: pip install modelscope'
        ) from exc

    class _SamModelScopeProgress(ProgressCallback):
        def __init__(self, filename: str, file_size: int):
            super().__init__(filename, file_size or ESTIMATED_MODEL_SIZE_BYTES)
            self._downloaded = _get_partial_bytes()

        def update(self, size: int) -> None:
            self._downloaded += int(size)
            total = self.file_size or ESTIMATED_MODEL_SIZE_BYTES
            _set_progress(
                'downloading',
                _calc_progress(self._downloaded, total),
                downloaded=self._downloaded,
                total=total,
            )

    staging_dir = _modelscope_staging_dir()
    os.makedirs(staging_dir, exist_ok=True)

    resume_bytes = _get_partial_bytes()
    stop_event = threading.Event()
    poller = threading.Thread(
        target=_poll_staging_file,
        args=(stop_event,),
        name='sam-modelscope-poll',
        daemon=True,
    )
    poller.start()
    try:
        _set_progress(
            'downloading',
            max(1, _calc_progress(resume_bytes, ESTIMATED_MODEL_SIZE_BYTES)),
            downloaded=resume_bytes,
            total=ESTIMATED_MODEL_SIZE_BYTES,
        )
        snapshot_download(
            model_id=SAM_MODELSCOPE_ID,
            revision=SAM_MODELSCOPE_REVISION,
            local_dir=staging_dir,
            allow_file_pattern=SAM_MODELSCOPE_FILE,
            progress_callbacks=[
                _SamModelScopeProgress(SAM_MODELSCOPE_FILE, ESTIMATED_MODEL_SIZE_BYTES),
            ],
        )
        downloaded_path = _modelscope_staging_file()
        if not os.path.isfile(downloaded_path):
            raise RuntimeError(
                f'ModelScope 下载完成但未找到 {SAM_MODELSCOPE_FILE}，'
                f'请检查模型 {SAM_MODELSCOPE_ID} 是否存在该文件'
            )
        _install_downloaded_file(downloaded_path)
    finally:
        stop_event.set()
        poller.join(timeout=2)


def _download_http_with_progress(url: str, dest_path: str) -> None:
    existing_size = _get_partial_bytes() if os.path.abspath(dest_path) == os.path.abspath(_partial_path()) else 0
    if os.path.isfile(dest_path) and existing_size == 0:
        try:
            existing_size = os.path.getsize(dest_path)
        except OSError:
            existing_size = 0

    headers = {'User-Agent': DOWNLOAD_USER_AGENT}
    if existing_size > 0:
        headers['Range'] = f'bytes={existing_size}-'

    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT_SEC)
    except urllib.error.HTTPError as exc:
        if exc.code == 416 and existing_size > 0:
            _finalize_partial(dest_path)
            return
        raise

    with resp:
        status_code = getattr(resp, 'status', None) or resp.getcode()
        content_length = int(resp.headers.get('Content-Length', 0) or 0)
        content_range = resp.headers.get('Content-Range', '') or ''
        total = _parse_content_range_total(content_range, content_length, existing_size)

        if status_code == 200 and existing_size > 0:
            existing_size = 0
            total = content_length or ESTIMATED_MODEL_SIZE_BYTES

        downloaded = existing_size
        _set_progress('downloading', max(1, _calc_progress(downloaded, total)), downloaded=downloaded, total=total)

        file_mode = 'ab' if existing_size > 0 and status_code == 206 else 'wb'
        if file_mode == 'wb':
            downloaded = 0

        with open(dest_path, file_mode) as out_file:
            while True:
                chunk = resp.read(DOWNLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)
                _set_progress(
                    'downloading',
                    _calc_progress(downloaded, total),
                    downloaded=downloaded,
                    total=total,
                )


def _prepare_download_state() -> None:
    resume_bytes = _get_partial_bytes()
    with _lock:
        _state['status'] = 'downloading'
        _state['stage'] = 'downloading'
        _state['error'] = None
        if resume_bytes > 0:
            total = int(_state['total_bytes']) or ESTIMATED_MODEL_SIZE_BYTES
            _state['downloaded_bytes'] = resume_bytes
            _state['total_bytes'] = total
            _state['progress'] = _calc_progress(resume_bytes, total)
        else:
            _state['progress'] = 0
            _state['downloaded_bytes'] = 0
            _state['total_bytes'] = ESTIMATED_MODEL_SIZE_BYTES


def _mark_download_done() -> None:
    with _lock:
        _state['status'] = 'done'
        _state['stage'] = 'done'
        _state['progress'] = 100
        _state['downloaded_bytes'] = os.path.getsize(SAM_MODEL_PATH)
        _state['total_bytes'] = _state['downloaded_bytes']
        _state['error'] = None


def _mark_download_error(exc: Exception) -> None:
    partial_bytes = _get_partial_bytes()
    with _lock:
        _state['status'] = 'error'
        _state['stage'] = 'error'
        _state['error'] = str(exc)
        if partial_bytes > 0:
            total = int(_state['total_bytes']) or ESTIMATED_MODEL_SIZE_BYTES
            _state['downloaded_bytes'] = partial_bytes
            _state['progress'] = _calc_progress(partial_bytes, total)


def _do_download() -> None:
    partial_path = _partial_path()
    try:
        if not _can_auto_download():
            raise RuntimeError(
                f'未配置 SAM 模型下载源。请设置 SAM_MODELSCOPE_ID（默认 facebook/sam3.1）'
                f'或 SAM_MODEL_DOWNLOAD_URL，或手动将权重放到 {SAM_MODEL_PATH}'
            )

        _prepare_download_state()
        os.makedirs(os.path.dirname(SAM_MODEL_PATH) or '.', exist_ok=True)

        if _download_source() == 'http':
            _download_http_with_progress(SAM_MODEL_DOWNLOAD_URL, partial_path)
            _finalize_partial(partial_path)
        else:
            _download_modelscope_with_progress()

        _mark_download_done()
    except Exception as exc:
        _mark_download_error(exc)
    finally:
        try:
            from app.services.sam_service import reset_sam_service
            reset_sam_service()
        except Exception:
            pass


def start_sam_model_download() -> Dict[str, Any]:
    with _lock:
        if is_sam_model_available():
            _state['status'] = 'done'
            _state['stage'] = 'done'
            _state['progress'] = 100
            _state['error'] = None
            return {'started': False, 'message': '模型已存在', **_build_status_locked()}

        if _state['status'] == 'downloading':
            return {'started': False, 'message': '模型正在下载中', **_build_status_locked()}

        resume_bytes = _get_partial_bytes()
        _state['status'] = 'downloading'
        _state['stage'] = 'downloading'
        _state['error'] = None
        if resume_bytes > 0:
            total = int(_state['total_bytes']) or ESTIMATED_MODEL_SIZE_BYTES
            _state['downloaded_bytes'] = resume_bytes
            _state['total_bytes'] = total
            _state['progress'] = _calc_progress(resume_bytes, total)
            message = f'已从 {_format_bytes(resume_bytes)} 处续传'
        else:
            _state['progress'] = 0
            _state['downloaded_bytes'] = 0
            _state['total_bytes'] = ESTIMATED_MODEL_SIZE_BYTES
            if _download_source() == 'modelscope':
                message = f'已开始从魔塔 ModelScope 下载 {SAM_MODELSCOPE_ID}'
            else:
                message = '已开始下载'
        status = _build_status_locked()

    thread = threading.Thread(target=_do_download, name='sam-model-download', daemon=True)
    thread.start()
    return {'started': True, 'message': message, **status}


def _format_bytes(num: int) -> str:
    if num >= 1024 * 1024 * 1024:
        return f'{num / (1024 * 1024 * 1024):.1f} GB'
    if num >= 1024 * 1024:
        return f'{num / (1024 * 1024):.1f} MB'
    if num >= 1024:
        return f'{num / 1024:.1f} KB'
    return f'{num} B'
