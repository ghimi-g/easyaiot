"""
人脸识别服务（ArcFace ONNX 特征提取 + Milvus 向量检索）
固定匹配模型：VIDEO/face_rec.onnx；检测复用 VIDEO/face_det.onnx
"""
import os
import threading
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import cv2
import numpy as np

from app.services.face_vector_store import get_face_vector_store
from app.utils.face_model_paths import FACE_MATCH_MODEL_PATH

try:
    from insightface.model_zoo import get_model as insightface_get_model
    _INSIGHTFACE_IMPORT_ERROR: Optional[Exception] = None
except Exception as exc:  # pragma: no cover
    insightface_get_model = None
    _INSIGHTFACE_IMPORT_ERROR = exc


def _to_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_embedding(feat: np.ndarray) -> np.ndarray:
    vec = feat.astype(np.float32).flatten()
    norm = np.linalg.norm(vec)
    if norm > 0:
        vec = vec / norm
    return vec


class FaceRecognitionService:
    def __init__(self):
        self._vector_store = get_face_vector_store()
        self.similarity_threshold = float(os.getenv("FACE_SIMILARITY_THRESHOLD", "0.55"))
        self.face_model_path = os.getenv("FACE_MATCH_MODEL_PATH", FACE_MATCH_MODEL_PATH)
        self._rec_model = None
        self._rec_model_lock = threading.Lock()

    @property
    def collection_name(self) -> str:
        return self._vector_store.collection_name

    @property
    def milvus_uri(self) -> str:
        return self._vector_store.milvus_uri

    def _ensure_rec_model(self):
        if _INSIGHTFACE_IMPORT_ERROR is not None or insightface_get_model is None:
            raise RuntimeError(f"InsightFace 未安装或加载失败: {_INSIGHTFACE_IMPORT_ERROR}")
        if self._rec_model is not None:
            return
        with self._rec_model_lock:
            if self._rec_model is not None:
                return
            if not os.path.isfile(self.face_model_path) or os.path.getsize(self.face_model_path) < 10 * 1024 * 1024:
                raise FileNotFoundError(
                    f"人脸匹配模型不存在或未完整下载: {self.face_model_path}，"
                    f"请在 WEB 人脸库页面或运行 install 脚本下载 {os.path.basename(self.face_model_path)}"
                )
            use_gpu = _to_bool(os.getenv("USE_GPU"), default=False)
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if use_gpu else ["CPUExecutionProvider"]
            self._rec_model = insightface_get_model(self.face_model_path, providers=providers)

    def _embed_crop(self, crop: np.ndarray) -> np.ndarray:
        self._ensure_rec_model()
        input_size = self._rec_model.input_size
        aligned = cv2.resize(crop, input_size)
        feat = self._rec_model.get_feat(aligned)
        return _normalize_embedding(feat)

    def _extract_faces(self, image: np.ndarray) -> List[Any]:
        from app.utils.face_capture_service import detect_faces

        detections = detect_faces(image)
        faces: List[Any] = []
        h, w = image.shape[:2]
        for det in detections:
            bbox = det.get("bbox") or []
            if len(bbox) < 4:
                continue
            x1, y1, x2, y2 = [int(v) for v in bbox[:4]]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            if x2 <= x1 or y2 <= y1:
                continue
            crop = image[y1:y2, x1:x2]
            if crop.size == 0:
                continue
            embedding = self._embed_crop(crop)
            faces.append(
                SimpleNamespace(
                    bbox=np.array([x1, y1, x2, y2], dtype=np.float32),
                    normed_embedding=embedding,
                )
            )
        return faces

    def _pick_largest_face(self, faces: List[Any]):
        if not faces:
            return None
        return max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))

    def add_face(self, label: str, image: np.ndarray) -> Dict[str, Any]:
        """兼容旧版单库 API"""
        faces = self._extract_faces(image)
        face = self._pick_largest_face(faces)
        if face is None:
            raise ValueError("图片中未检测到人脸")
        embedding = face.normed_embedding.astype(np.float32)
        inserted = self._vector_store.insert_embedding(
            embedding, label=label, library_id=0,
        )
        return {"insert_result": inserted.get("insert_result"), "face_count": len(faces),
                "milvus_id": inserted.get("milvus_id")}

    def add_face_to_library(self, library_id: int, face_entry_id: int, person_name: str,
                            image: np.ndarray, person_code: Optional[str] = None) -> Dict[str, Any]:
        faces = self._extract_faces(image)
        face = self._pick_largest_face(faces)
        if face is None:
            raise ValueError("图片中未检测到人脸")
        embedding = face.normed_embedding.astype(np.float32)
        inserted = self._vector_store.insert_embedding(
            embedding,
            label=person_name,
            library_id=library_id,
            face_entry_id=face_entry_id,
            person_name=person_name,
            person_code=person_code or "",
        )
        return {"insert_result": inserted.get("insert_result"), "face_count": len(faces),
                "milvus_id": inserted.get("milvus_id")}

    def update_face_entry_id(self, milvus_id, face_entry_id: int) -> None:
        self._vector_store.update_face_entry_id(milvus_id, face_entry_id)

    def update_face(self, label: str, image: np.ndarray) -> Dict[str, Any]:
        deleted = self.delete_face(label)
        added = self.add_face(label, image)
        return {"deleted": deleted, "added": added}

    def delete_face(self, label: str) -> int:
        return self._vector_store.delete_face(label)

    def delete_by_milvus_id(self, milvus_id) -> None:
        self._vector_store.delete_by_milvus_id(milvus_id)

    def list_faces(self, label: Optional[str] = None, limit: int = 1000) -> List[Dict[str, Any]]:
        return self._vector_store.list_faces(label=label, limit=limit)

    def recognize(self, image: np.ndarray, top_k: int = 3, library_id: Optional[int] = None,
                  threshold: Optional[float] = None) -> Dict[str, Any]:
        use_threshold = float(threshold) if threshold is not None else self.similarity_threshold
        faces = self._extract_faces(image)
        if not faces:
            return {"face_count": 0, "results": [], "threshold": use_threshold}

        result_list: List[Dict[str, Any]] = []
        for face in faces:
            embedding = face.normed_embedding.astype(np.float32)
            candidates = self._vector_store.search_embedding(
                embedding, top_k=top_k, library_id=library_id,
            )
            for item in candidates:
                item["matched"] = item.get("similarity", 0) >= use_threshold
            best = candidates[0] if candidates else None
            x1, y1, x2, y2 = [int(v) for v in face.bbox.tolist()]
            result_list.append({
                "bbox": [x1, y1, x2, y2],
                "matched": bool(best and best.get("matched")),
                "best_match": best,
                "candidates": candidates,
            })
        return {"face_count": len(faces), "results": result_list, "threshold": use_threshold}

    def match_in_library(self, library_id: int, image: np.ndarray, threshold: float,
                         top_k: int = 5) -> Dict[str, Any]:
        faces = self._extract_faces(image)
        face = self._pick_largest_face(faces)
        if face is None:
            return {
                "face_count": 0,
                "matched": False,
                "best_match": None,
                "candidates": [],
                "threshold": threshold,
            }
        embedding = face.normed_embedding.astype(np.float32)
        candidates = self._vector_store.search_embedding(
            embedding, top_k=top_k, library_id=library_id,
        )
        for item in candidates:
            item["matched"] = item.get("similarity", 0) >= threshold
        best = candidates[0] if candidates else None
        x1, y1, x2, y2 = [int(v) for v in face.bbox.tolist()]
        return {
            "face_count": 1,
            "bbox": [x1, y1, x2, y2],
            "matched": bool(best and best.get("matched")),
            "best_match": best,
            "candidates": candidates,
            "threshold": threshold,
        }

    def extract_and_crop_largest_face(self, image: np.ndarray) -> Optional[Dict[str, Any]]:
        faces = self._extract_faces(image)
        face = self._pick_largest_face(faces)
        if face is None:
            return None
        x1, y1, x2, y2 = [int(v) for v in face.bbox.tolist()]
        h, w = image.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        crop = image[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        embedding = face.normed_embedding.astype(np.float32)
        return {
            "bbox": [x1, y1, x2, y2],
            "crop": crop,
            "embedding": embedding,
        }

    def ping(self) -> Dict[str, Any]:
        data = self._vector_store.ping()
        data["face_matching_model"] = os.path.basename(self.face_model_path)
        data["face_matching_model_path"] = self.face_model_path
        data["recognition_model_loaded"] = self._rec_model is not None
        return data


_FACE_SERVICE_LOCK = threading.Lock()
_FACE_SERVICE_INSTANCE: Optional[FaceRecognitionService] = None


def get_face_recognition_service() -> FaceRecognitionService:
    global _FACE_SERVICE_INSTANCE
    if _FACE_SERVICE_INSTANCE is not None:
        return _FACE_SERVICE_INSTANCE
    with _FACE_SERVICE_LOCK:
        if _FACE_SERVICE_INSTANCE is None:
            _FACE_SERVICE_INSTANCE = FaceRecognitionService()
    return _FACE_SERVICE_INSTANCE


def decode_image_bytes(image_bytes: bytes) -> np.ndarray:
    if not image_bytes:
        raise ValueError("图片数据为空")
    frame = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("图片解码失败，请检查图片格式")
    return frame
