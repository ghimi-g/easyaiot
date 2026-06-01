"""人脸特征提取模型 face_rec.onnx 下载与状态查询"""
import os
import threading
import tempfile
import urllib.request
import zipfile
from typing import Any, Dict

from app.utils.face_model_paths import FACE_MATCH_MODEL_PATH

FACE_REC_DOWNLOAD_URL = os.getenv(
    'FACE_REC_MODEL_DOWNLOAD_URL',
    'https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip',
)
ONNX_IN_ZIP = 'buffalo_l/w600k_r50.onnx'
# 完整模型约 167MB，低于此阈值视为未下载或损坏
MIN_MODEL_SIZE_BYTES = 10 * 1024 * 1024

_lock = threading.Lock()
_state: Dict[str, Any] = {
    'status': 'idle',  # idle | downloading | done | error
    'progress': 0,
    'error': None,
}


def _reset_error_if_idle() -> None:
    if _state['status'] == 'idle':
        _state['error'] = None


def is_face_rec_model_available() -> bool:
    if not os.path.isfile(FACE_MATCH_MODEL_PATH):
        return False
    try:
        return os.path.getsize(FACE_MATCH_MODEL_PATH) >= MIN_MODEL_SIZE_BYTES
    except OSError:
        return False


def _build_status_locked() -> Dict[str, Any]:
    exists = is_face_rec_model_available()
    size_bytes = os.path.getsize(FACE_MATCH_MODEL_PATH) if exists else 0
    _reset_error_if_idle()
    return {
        'exists': exists,
        'filename': os.path.basename(FACE_MATCH_MODEL_PATH),
        'path': FACE_MATCH_MODEL_PATH,
        'size_bytes': size_bytes,
        'downloading': _state['status'] == 'downloading',
        'progress': int(_state['progress']),
        'error': _state['error'],
    }


def get_face_rec_model_status() -> Dict[str, Any]:
    with _lock:
        return _build_status_locked()


def _download_with_progress(url: str, dest_path: str) -> None:
    def _report(block_num: int, block_size: int, total_size: int) -> None:
        if total_size <= 0:
            return
        progress = min(99, int(block_num * block_size * 100 / total_size))
        with _lock:
            _state['progress'] = progress

    urllib.request.urlretrieve(url, dest_path, reporthook=_report)


def _extract_onnx(zip_path: str, target_path: str) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open(ONNX_IN_ZIP) as src, open(target_path, 'wb') as dst:
            while True:
                chunk = src.read(1024 * 1024)
                if not chunk:
                    break
                dst.write(chunk)


def _do_download() -> None:
    tmp_dir = tempfile.mkdtemp(prefix='face_rec_model_')
    zip_path = os.path.join(tmp_dir, 'buffalo_l.zip')
    partial_path = f'{FACE_MATCH_MODEL_PATH}.downloading'
    try:
        with _lock:
            _state['status'] = 'downloading'
            _state['progress'] = 0
            _state['error'] = None

        _download_with_progress(FACE_REC_DOWNLOAD_URL, zip_path)

        with _lock:
            _state['progress'] = 99

        _extract_onnx(zip_path, partial_path)
        os.replace(partial_path, FACE_MATCH_MODEL_PATH)

        with _lock:
            _state['status'] = 'done'
            _state['progress'] = 100
            _state['error'] = None
    except Exception as exc:
        for path in (partial_path, FACE_MATCH_MODEL_PATH):
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        with _lock:
            _state['status'] = 'error'
            _state['error'] = str(exc)
    finally:
        try:
            if os.path.isfile(zip_path):
                os.remove(zip_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass


def start_face_rec_model_download() -> Dict[str, Any]:
    with _lock:
        if is_face_rec_model_available():
            _state['status'] = 'done'
            _state['progress'] = 100
            _state['error'] = None
            return {'started': False, 'message': '模型已存在', **_build_status_locked()}

        if _state['status'] == 'downloading':
            return {'started': False, 'message': '模型正在下载中', **_build_status_locked()}

        _state['status'] = 'downloading'
        _state['progress'] = 0
        _state['error'] = None
        status = _build_status_locked()

    thread = threading.Thread(target=_do_download, name='face-rec-model-download', daemon=True)
    thread.start()
    return {'started': True, 'message': '已开始下载', **status}
