# -*- coding: utf-8 -*-
"""
Unicode-safe image IO helpers.

WHY THIS FILE EXISTS (measured, not guessed):

On this machine (Windows + opencv-python 5.0.0), cv2.imread CANNOT open a path
that contains non-ASCII characters (e.g. the Chinese file name of the test
images) ... unless something else in the process has already imported
ultralytics / torch, which silently changes the behaviour.

Measured with app/diag_imread.py: 6 of 8 Chinese paths failed before importing
ultralytics, 0 of 8 failed afterwards.

That makes cv2.imread unreliable: in the real GUI the user picks a photo BEFORE
the YOLO model is loaded, so the very first "choose image" fails. Therefore every
user-supplied path goes through np.fromfile + cv2.imdecode, which is
deterministic and worked 8/8 in the same measurement.
"""

import cv2
import numpy as np


def imread_unicode(path):
    """Read an image from any path (including non-ASCII). None on failure."""
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
        if buf.size == 0:
            return None
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        return None


def imwrite_unicode(path, image_bgr, quality=92):
    """Write an image to any path (including non-ASCII). True on success."""
    try:
        s = str(path)
        ext = "." + s.rsplit(".", 1)[-1].lower() if "." in s else ".jpg"
        params = [cv2.IMWRITE_JPEG_QUALITY, quality] if ext in (".jpg", ".jpeg") else []
        ok, buf = cv2.imencode(ext, image_bgr, params)
        if not ok:
            return False
        buf.tofile(s)
        return True
    except Exception:
        return False
