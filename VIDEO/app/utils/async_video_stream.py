"""
OpenCV 网络流异步解码：后台线程持续 VideoCapture.read()，主线程取最新帧拷贝。
供 realtime_algorithm_service、stream_forward_service、snapshot_algorithm_service 等共用。

环境变量：AI_RTSP_ASYNC_READ（默认开启），见 VIDEO/docs/realtime_algorithm_rtsp_async_read.md。
"""
from __future__ import annotations

import os
import threading
from typing import Optional

import cv2


class AsyncVideoStream:
    """
    后台线程持续调用 VideoCapture.read() 解码，主线程只取锁内最新帧。
    缓解 OpenCV read() 与业务逻辑串行导致的有效帧率被摄像头 fps 限制、灰屏误检等问题。
    """

    def __init__(self, capture: cv2.VideoCapture):
        self._cap = capture
        self._lock = threading.Lock()
        self._frame = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self.read_failed = False

    def isOpened(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def set(self, prop, value):
        return self._cap.set(prop, value)

    def read(self):
        """与 cv2.VideoCapture.read 一致，返回 (ret, frame)。"""
        if self.read_failed:
            return False, None
        with self._lock:
            if self._frame is None:
                return False, None
            return True, self._frame.copy()

    def start(self):
        self._running = True
        self.read_failed = False
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
        return self

    def _update_loop(self):
        try:
            while self._running:
                ret, frame = self._cap.read()
                if not ret or frame is None:
                    # 仅在仍视为“运行中”时标记失败，避免 release() 后 read 返回误触发重连
                    if self._running:
                        self.read_failed = True
                    break
                with self._lock:
                    self._frame = frame
        except Exception:
            if self._running:
                self.read_failed = True

    def release(self):
        self._running = False
        cap = self._cap
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        self._cap = None
        with self._lock:
            self._frame = None


def async_rtsp_read_enabled() -> bool:
    """是否对 rtsp/rtmp 使用异步拉流（默认开启）。"""
    v = (os.getenv("AI_RTSP_ASYNC_READ", "1") or "1").strip().lower()
    return v not in ("0", "false", "no", "off")
