# -*- coding: utf-8 -*-
"""
Camera interface layer.
=======================
Current build has no industrial camera, so we only provide mock / file
backends. When a real camera arrives, implement the same four methods
(start / stop / get_frame / is_connected) and swap the class used by the GUI.

All methods are read-only with respect to project data.
"""

from pathlib import Path

import cv2
import numpy as np

from .imageio_util import imread_unicode


class CameraBase:
    """Common interface: start(), stop(), get_frame(), is_connected()."""

    name = "base"

    def start(self) -> bool:
        raise NotImplementedError

    def stop(self) -> None:
        raise NotImplementedError

    def get_frame(self):
        raise NotImplementedError

    def is_connected(self) -> bool:
        raise NotImplementedError

    def set_source(self, source) -> None:
        """Optional: point the camera at a file. A real camera ignores this."""
        return None


class ImageFileCamera(CameraBase):
    """Reads one still image from disk (acts as a stand-in for the camera)."""

    name = "image_file"

    def __init__(self, image_path=None):
        self._path = Path(image_path) if image_path else None
        self._running = False
        self._frame = None

    def set_image(self, image_path):
        self.set_source(image_path)

    def set_source(self, source) -> None:
        self._path = Path(source) if source else None

    def start(self) -> bool:
        if self._path is None or not self._path.is_file():
            self._running = False
            return False
        # Unicode-safe read: cv2.imread is unreliable for non-ASCII paths here.
        self._frame = imread_unicode(self._path)
        self._running = self._frame is not None
        return self._running

    def stop(self) -> None:
        self._running = False
        self._frame = None

    def get_frame(self):
        if self._frame is None:
            return None
        return self._frame.copy()

    def is_connected(self) -> bool:
        # A file is not a live camera, so we report "not connected" honestly.
        return False

    @property
    def source_path(self):
        return str(self._path) if self._path else None


class MockCamera(CameraBase):
    """Synthetic camera for demos / tests: produces a blank image."""

    name = "mock"

    def __init__(self, width=1280, height=720):
        self._w, self._h = width, height
        self._running = False

    def start(self) -> bool:
        self._running = True
        return True

    def stop(self) -> None:
        self._running = False

    def get_frame(self):
        if not self._running:
            return None
        return np.full((self._h, self._w, 3), 60, np.uint8)

    def is_connected(self) -> bool:
        return False


def create_camera(image_path=None, prefer="file") -> CameraBase:
    """Factory used by the GUI. Swap the body here when a real camera is added."""
    if prefer == "mock":
        return MockCamera()
    return ImageFileCamera(image_path)
