"""
SAM 万物识别服务 — SAM3 文本/框选推理（进程内单例）
"""
import base64
import logging
import os
import threading
import time
from typing import Any, Optional

import cv2
import numpy as np
import requests

logger = logging.getLogger(__name__)

_AI_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_SAM_MODEL_PATH = os.path.join(_AI_ROOT, 'models', 'sam3', 'sam3.1_multiplex.pt')

SAM_ENABLED = os.getenv('SAM_ENABLED', 'false').lower() in ('1', 'true', 'yes')
SAM_ENGINE = os.getenv('SAM_ENGINE', 'sam3')
SAM_MODEL_PATH = os.getenv('SAM_MODEL_PATH', _DEFAULT_SAM_MODEL_PATH)
SAM_CONF = float(os.getenv('SAM_CONF', '0.45'))
SAM_IMGSZ = int(os.getenv('SAM_IMGSZ', '1078'))
SAM_TIMEOUT = float(os.getenv('SAM_TIMEOUT', '30'))
SAM_MAX_IMAGE_BYTES = int(os.getenv('SAM_MAX_IMAGE_BYTES', str(10 * 1024 * 1024)))
SAM_WORKER_URL = os.getenv('SAM_WORKER_URL', '').rstrip('/')
SAM_WARMUP_IMAGE = os.getenv('SAM_WARMUP_IMAGE', '')
SAM_WARMUP_TEXT = os.getenv('SAM_WARMUP_TEXT', 'person')

_service_instance = None
_service_lock = threading.Lock()


def get_sam_service():
    global _service_instance
    if _service_instance is None:
        with _service_lock:
            if _service_instance is None:
                _service_instance = SamService()
    return _service_instance


def reset_sam_service():
    """模型下载完成后重置单例，使下次推理重新加载权重。"""
    global _service_instance
    with _service_lock:
        _service_instance = None


class SamService:
    """SAM3 推理单例，参考 sam-changkang ModelService 设计。"""

    def __init__(self):
        self._predictor = None
        self._model_lock = threading.Lock()
        self._initialized = False
        self._warmup_done = False
        self._device = 'cpu'
        self._engine = SAM_ENGINE

    @property
    def enabled(self) -> bool:
        return SAM_ENABLED or bool(SAM_WORKER_URL)

    @property
    def model_loaded(self) -> bool:
        if SAM_WORKER_URL:
            return True
        return self._initialized and self._predictor is not None

    def get_device(self) -> str:
        return self._device

    def warmup_if_needed(self):
        if self._warmup_done or SAM_WORKER_URL:
            return
        try:
            if SAM_WARMUP_IMAGE and os.path.isfile(SAM_WARMUP_IMAGE):
                self.predict(SAM_WARMUP_IMAGE, text=[SAM_WARMUP_TEXT], return_masks=False)
            else:
                dummy = np.zeros((64, 64, 3), dtype=np.uint8)
                self.predict(dummy, text=[SAM_WARMUP_TEXT], return_masks=False)
            self._warmup_done = True
        except Exception as e:
            logger.warning('SAM warmup 失败（不影响后续请求）: %s', e)

    def _ensure_model(self):
        if self._initialized:
            return
        if SAM_WORKER_URL:
            self._initialized = True
            return
        if not SAM_ENABLED:
            raise RuntimeError('SAM 未启用，请设置 SAM_ENABLED=true 或配置 SAM_WORKER_URL')
        try:
            import torch
            self._device = 'cuda:0' if torch.cuda.is_available() else 'cpu'
        except Exception:
            self._device = 'cpu'

        if SAM_ENGINE == 'sam3':
            try:
                from ultralytics.models.sam import SAM3SemanticPredictor
                overrides = dict(
                    conf=SAM_CONF,
                    imgsz=SAM_IMGSZ,
                    task='segment',
                    mode='predict',
                    model=SAM_MODEL_PATH,
                    half=self._device.startswith('cuda'),
                    save=False,
                    device=self._device,
                )
                self._predictor = SAM3SemanticPredictor(overrides=overrides)
                self._engine = 'sam3'
                logger.info('SAM3 模型加载成功: %s device=%s', SAM_MODEL_PATH, self._device)
            except Exception as e:
                logger.error('SAM3 模型加载失败: %s', e)
                raise RuntimeError(f'SAM3 模型加载失败: {e}') from e
        else:
            raise RuntimeError(f'不支持的 SAM 引擎: {SAM_ENGINE}')
        self._initialized = True

    def predict(
        self,
        image,
        *,
        text: Optional[list] = None,
        bboxes: Optional[list] = None,
        return_masks: bool = True,
        conf: Optional[float] = None,
        imgsz: Optional[int] = None,
    ) -> dict:
        """推理入口。image 可为文件路径、BGR ndarray 或 RGB ndarray。"""
        if SAM_WORKER_URL:
            return self._predict_via_worker(image, text=text, bboxes=bboxes,
                                            return_masks=return_masks, conf=conf, imgsz=imgsz)

        if not self._model_lock.acquire(timeout=SAM_TIMEOUT):
            raise TimeoutError('SAM 推理排队超时')

        t0 = time.perf_counter()
        try:
            self._ensure_model()
            bgr = self._to_bgr(image)
            if bgr is None:
                raise ValueError('无法解码输入图像')

            h, w = bgr.shape[:2]
            conf_val = conf if conf is not None else SAM_CONF
            imgsz_val = imgsz if imgsz is not None else SAM_IMGSZ

            if text and bboxes:
                raise ValueError('text 与 bboxes 不能同时指定')
            if not text and not bboxes:
                raise ValueError('请提供 text 或 bboxes')

            prompt_type = 'text' if text else 'box'
            kwargs: dict[str, Any] = {'conf': conf_val, 'imgsz': imgsz_val}
            if text:
                kwargs['text'] = text
            if bboxes:
                kwargs['bboxes'] = bboxes

            results = self._predictor(source=bgr, **kwargs)
            parsed = self._parse_results(results, w, h, prompt_type, return_masks)
            parsed['inference_ms'] = int((time.perf_counter() - t0) * 1000)
            parsed['engine'] = self._engine
            parsed['prompt_type'] = prompt_type
            parsed['orig_shape'] = [h, w]
            return parsed
        finally:
            self._model_lock.release()

    def _predict_via_worker(self, image, **kwargs) -> dict:
        import tempfile
        files = None
        data = {
            'return_masks': str(kwargs.get('return_masks', True)).lower(),
        }
        if kwargs.get('conf') is not None:
            data['conf'] = str(kwargs['conf'])
        if kwargs.get('text'):
            import json
            data['text'] = json.dumps(kwargs['text'])
        if kwargs.get('bboxes'):
            import json
            data['bboxes'] = json.dumps(kwargs['bboxes'])

        if isinstance(image, str):
            with open(image, 'rb') as f:
                files = {'file': f}
                resp = requests.post(f'{SAM_WORKER_URL}/model/sam/predict', files=files, data=data,
                                     timeout=SAM_TIMEOUT + 10)
        elif isinstance(image, np.ndarray):
            ok, buf = cv2.imencode('.jpg', self._to_bgr(image))
            if not ok:
                raise ValueError('图像编码失败')
            files = {'file': ('image.jpg', buf.tobytes(), 'image/jpeg')}
            resp = requests.post(f'{SAM_WORKER_URL}/model/sam/predict', files=files, data=data,
                                 timeout=SAM_TIMEOUT + 10)
        else:
            raise ValueError('不支持的图像类型')

        resp.raise_for_status()
        body = resp.json()
        if body.get('code') != 0:
            raise RuntimeError(body.get('msg', 'SAM Worker 推理失败'))
        return body.get('data') or {}

    @staticmethod
    def _to_bgr(image) -> Optional[np.ndarray]:
        if isinstance(image, np.ndarray):
            if image.ndim == 2:
                return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
            if image.shape[2] == 4:
                return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
            return image.copy()
        if isinstance(image, str):
            if not os.path.isfile(image):
                raise FileNotFoundError(image)
            bgr = cv2.imread(image)
            return bgr
        return None

    @staticmethod
    def decode_image_bytes(data: bytes) -> np.ndarray:
        arr = np.frombuffer(data, dtype=np.uint8)
        bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if bgr is None:
            raise ValueError('图像解码失败')
        return bgr

    @staticmethod
    def decode_base64_image(b64_str: str) -> np.ndarray:
        if not b64_str:
            raise ValueError('image_base64 为空')
        if b64_str.startswith('data:'):
            b64_str = b64_str.split(',', 1)[1]
        raw = base64.b64decode(b64_str)
        if len(raw) > SAM_MAX_IMAGE_BYTES:
            raise ValueError(f'图片超过 {SAM_MAX_IMAGE_BYTES} 字节限制')
        return SamService.decode_image_bytes(raw)

    @staticmethod
    def download_image_url(url: str) -> np.ndarray:
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        if len(resp.content) > SAM_MAX_IMAGE_BYTES:
            raise ValueError(f'图片超过 {SAM_MAX_IMAGE_BYTES} 字节限制')
        return SamService.decode_image_bytes(resp.content)

    def _parse_results(self, results, img_w, img_h, prompt_type, return_masks) -> dict:
        predictions = []
        masks_out = []

        result_list = results if isinstance(results, list) else [results]
        for res in result_list:
            boxes = getattr(res, 'boxes', None)
            if boxes is not None and len(boxes):
                xyxy = boxes.xyxy.cpu().numpy() if hasattr(boxes.xyxy, 'cpu') else np.array(boxes.xyxy)
                confs = boxes.conf.cpu().numpy() if hasattr(boxes.conf, 'cpu') else np.array(boxes.conf)
                cls_names = None
                if hasattr(boxes, 'cls_name'):
                    cls_names = boxes.cls_name
                elif hasattr(res, 'names'):
                    cls_ids = boxes.cls.cpu().numpy() if hasattr(boxes.cls, 'cpu') else np.array(boxes.cls)
                    names = res.names
                    if isinstance(names, (list, tuple)):
                        names = {idx: nm for idx, nm in enumerate(names)}
                    cls_names = [names.get(int(c), str(int(c))) for c in cls_ids]

                for i in range(len(xyxy)):
                    x1, y1, x2, y2 = [float(v) for v in xyxy[i][:4]]
                    cls_name = cls_names[i] if cls_names is not None else f'class_{i}'
                    if isinstance(cls_name, (int, float)):
                        cls_name = str(int(cls_name))
                    predictions.append({
                        'class': i,
                        'class_name': str(cls_name),
                        'confidence': float(confs[i]) if i < len(confs) else 0.0,
                        'bbox': [x1, y1, x2, y2],
                    })

            if return_masks:
                seg_masks = getattr(res, 'masks', None)
                if seg_masks is not None and len(seg_masks):
                    xy_list = seg_masks.xy if hasattr(seg_masks, 'xy') else []
                    confs = boxes.conf.cpu().numpy() if boxes is not None and hasattr(boxes.conf, 'cpu') else []
                    cls_names = None
                    if boxes is not None and hasattr(boxes, 'cls_name'):
                        cls_names = boxes.cls_name
                    for i, contour_pts in enumerate(xy_list):
                        if contour_pts is None or len(contour_pts) < 3:
                            continue
                        pts = [[float(x), float(y)] for x, y in contour_pts]
                        xyn = [[x / img_w, y / img_h] for x, y in pts]
                        cls_name = cls_names[i] if cls_names and i < len(cls_names) else f'class_{i}'
                        masks_out.append({
                            'class_name': str(cls_name),
                            'confidence': float(confs[i]) if i < len(confs) else 0.0,
                            'xy': [pts],
                            'xyn': [xyn],
                            'contour_count': 1,
                        })
                elif predictions:
                    for pred in predictions:
                        mask_entry = self._bbox_to_mask_contour(pred['bbox'], img_w, img_h)
                        if mask_entry:
                            mask_entry['class_name'] = pred['class_name']
                            mask_entry['confidence'] = pred['confidence']
                            masks_out.append(mask_entry)

        return {
            'predictions': predictions,
            'masks': masks_out if return_masks else [],
        }

    @staticmethod
    def _bbox_to_mask_contour(bbox, img_w, img_h) -> Optional[dict]:
        x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(img_w, x2), min(img_h, y2)
        if x2 <= x1 or y2 <= y1:
            return None
        pts = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
        xyn = [[x / img_w, y / img_h] for x, y in pts]
        return {'xy': [pts], 'xyn': [xyn], 'contour_count': 1}
