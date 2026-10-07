# -*- coding: utf-8 -*-
"""
Vision layer: YOLO-Seg inference + mask -> largest contour -> ellipse -> centre
=============================================================================
Separated from the GUI on purpose:
  * the GUI only calls ``HoleDetector.detect(...)`` and reads plain dicts;
  * no training code lives here (``model.train`` is never called);
  * the model file is only ever read.

Numbering uses the existing project convention: PCA on the four ellipse
centres, sort along the principal axis. This is a *current-image* numbering,
NOT a permanent physical identity, therefore ``orientation_status`` is
reported as "uncertain".
"""

import time
from pathlib import Path

import cv2
import numpy as np

from config import (CONF, DEVICE_PREFERENCE, EXPECTED_HOLES, IMGSZ, IOU,
                    MODEL_PATH, ORIENTATION_METHOD, ORIENTATION_NOTE,
                    ORIENTATION_STATUS)
from imageio_util import imread_unicode, imwrite_unicode  # noqa: F401  (re-exported)


def ellipse_from_mask(mask_bool):
    """Largest external contour -> cv2.fitEllipse. Returns (ellipse, contour)."""
    m = (mask_bool.astype(np.uint8)) * 255
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None, None
    cnt = max(contours, key=cv2.contourArea)
    if len(cnt) < 5:
        return None, cnt
    return cv2.fitEllipse(cnt), cnt


class HoleDetector:
    """Lazy-loading YOLO-Seg detector. Loads the model once, reuses it."""

    def __init__(self, weights=MODEL_PATH):
        self.weights = Path(weights)
        self._model = None
        self.device_used = None
        self.load_error = None

    # ------------------------------------------------------------------ load
    def load(self):
        if self._model is not None:
            return True
        if not self.weights.is_file():
            self.load_error = "模型文件不存在: {}".format(self.weights)
            return False
        try:
            from ultralytics import YOLO
        except Exception as exc:
            self.load_error = "无法导入 ultralytics: {}".format(exc)
            return False
        try:
            self._model = YOLO(str(self.weights))
        except Exception as exc:
            self.load_error = "模型加载失败: {}".format(exc)
            return False
        self.load_error = None
        return True

    # ---------------------------------------------------------------- device
    def _resolve_device(self):
        """GPU first, fall back to CPU. Returns (device_arg, warning_or_None)."""
        try:
            import torch
            if torch.cuda.is_available():
                return DEVICE_PREFERENCE[0], None
            return "cpu", "CUDA 不可用，已自动切换到 CPU 推理（较慢）"
        except Exception as exc:
            return "cpu", "无法检测 GPU（{}），使用 CPU".format(exc)

    # ---------------------------------------------------------------- detect
    def detect(self, image_path, conf=CONF, imgsz=IMGSZ):
        """Run inference and return a plain dict (never raises for user errors)."""
        result = {"image_path": str(image_path), "image_size": None, "expected": EXPECTED_HOLES,
                  "detections": 0, "complete": False, "holes": [], "avg_conf": None,
                  "orientation_status": ORIENTATION_STATUS,
                  "orientation_method": ORIENTATION_METHOD,
                  "orientation_note": ORIENTATION_NOTE,
                  "warnings": [], "errors": [], "device_used": None, "elapsed_s": None}

        p = Path(image_path) if image_path else None
        if p is None or not p.is_file():
            result["errors"].append("图片不存在或未选择: {}".format(image_path))
            return result

        img = imread_unicode(p)
        if img is None:
            result["errors"].append("图片读取失败（可能已损坏或格式不支持）: {}".format(p))
            return result
        h, w = img.shape[:2]
        result["image_size"] = [w, h]

        if not self.load():
            result["errors"].append(self.load_error or "模型加载失败")
            return result

        device, warn = self._resolve_device()
        result["device_used"] = device
        if warn:
            result["warnings"].append(warn)

        t0 = time.time()
        try:
            r = self._model.predict(source=str(p), conf=conf, iou=IOU, imgsz=imgsz,
                                    device=device, retina_masks=True, verbose=False)[0]
        except Exception as exc:
            result["errors"].append("YOLO 推理失败: {}".format(exc))
            return result

        n = 0 if r.masks is None else len(r.masks)
        raw = []
        for i in range(n):
            try:
                mask = r.masks.data[i].cpu().numpy() > 0.5
                conf_i = float(r.boxes.conf[i].cpu().numpy())
                ell, cnt = ellipse_from_mask(mask)
                if ell is None:
                    result["warnings"].append("第 {} 个目标的 mask 无法拟合椭圆，已跳过".format(i + 1))
                    continue
                (cx, cy), (MA, ma), ang = ell
                # IMPORTANT: OpenCV returns ((cx,cy), (axis1, axis2), angle) where
                # `angle` belongs to axis1. Swapping the two axes without rotating
                # the angle by 90 deg produces a wrong, visibly "poor" fit, so we
                # keep the original pairing and only ADD major/minor as extras.
                raw.append({"center": (float(cx), float(cy)), "confidence": conf_i,
                            "ellipse": {"center": [round(float(cx), 2), round(float(cy), 2)],
                                        "width": round(float(MA), 2),
                                        "height": round(float(ma), 2),
                                        "angle": round(float(ang), 2),
                                        "major": round(float(max(MA, ma)), 2),
                                        "minor": round(float(min(MA, ma)), 2),
                                        "aspect": round(float(min(MA, ma) / max(MA, ma)), 3)},
                            "contour": cnt, "mask": mask,
                            "class_name": r.names.get(int(r.boxes.cls[i].cpu().numpy()), "?")})
            except Exception as exc:
                result["warnings"].append("解析第 {} 个目标失败: {}".format(i + 1, exc))

        result["elapsed_s"] = round(time.time() - t0, 3)
        if not raw:
            result["errors"].append("未检测到任何 cylinder_bore 目标")
            return result

        raw.sort(key=lambda d: d["confidence"], reverse=True)
        raw = raw[:EXPECTED_HOLES]
        holes = self._number(raw)
        result["holes"] = holes
        result["detections"] = len(holes)
        result["complete"] = (len(holes) == EXPECTED_HOLES)
        result["avg_conf"] = round(float(np.mean([h["confidence"] for h in holes])), 4)
        if not result["complete"]:
            result["warnings"].append(
                "检测不完整：期望 {} 个目标，仅识别到 {} 个；未伪造缺失目标。".format(
                    EXPECTED_HOLES, len(holes)))
        return result

    @staticmethod
    def _number(raw):
        """PCA ordering -> H01..H04. Keeps 2D/3D shapes for drawing."""
        pts = np.array([d["center"] for d in raw], float)
        if len(pts) >= 2:
            mean = pts.mean(axis=0)
            _, _, vt = np.linalg.svd(pts - mean, full_matrices=False)
            axis = vt[0]
            if axis[0] < 0:          # reproducible, not physical
                axis = -axis
            order = np.argsort((pts - mean) @ axis)
        else:
            order = list(range(len(raw)))
        holes = []
        for idx, i in enumerate(order, 1):
            d = raw[i]
            holes.append({"id": "H{:02d}".format(idx),
                          "center_px": [round(d["center"][0], 2), round(d["center"][1], 2)],
                          "confidence": round(float(d["confidence"]), 4),
                          "ellipse": d["ellipse"],
                          "orientation_status": ORIENTATION_STATUS,
                          "status": "detected",
                          "class_name": d.get("class_name", "cylinder_bore"),
                          "_contour": d["contour"], "_mask": d["mask"]})
        return holes


# ------------------------------------------------------------------ drawing
def draw_result(image_bgr, result):
    """Draw mask outline, ellipse, centre and H0x labels onto a copy."""
    vis = image_bgr.copy()
    holes = result.get("holes", [])
    overlay = vis.copy()
    for h in holes:
        m = h.get("_mask")
        if m is not None:
            overlay[m] = (60, 200, 60)
    vis = cv2.addWeighted(overlay, 0.28, vis, 0.72, 0)

    for h in holes:
        cnt = h.get("_contour")
        if cnt is not None:
            cv2.drawContours(vis, [cnt], -1, (255, 255, 255), 3)
        e = h["ellipse"]
        (cx, cy) = e["center"]
        box = ((cx, cy), (max(e["width"], 1), max(e["height"], 1)), e["angle"])
        cv2.ellipse(vis, box, (0, 255, 0), 4)
        cv2.circle(vis, (int(cx), int(cy)), 9, (0, 0, 255), -1)
        cv2.circle(vis, (int(cx), int(cy)), 13, (255, 255, 255), 3)
        label = "{}  {:.2f}".format(h["id"], h["confidence"])
        org = (int(cx) + 18, int(cy) - 18)
        # text height follows hole size so it stays readable on any zoom
        fs = float(np.clip(min(e["major"], e["minor"]) / 260.0, 1.2, 4.0))
        th = max(2, int(round(fs * 2.2)))
        cv2.putText(vis, label, org, cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), th, cv2.LINE_AA)
        cv2.putText(vis, label, org, cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 255, 255),
                    max(2, th // 3), cv2.LINE_AA)

    hdr = "detected {}/{}  |  numbering: current-image PCA (uncertain)".format(
        result.get("detections", 0), result.get("expected", EXPECTED_HOLES))
    hfs = max(1.2, vis.shape[1] / 1800.0)
    cv2.putText(vis, hdr, (24, int(30 + hfs * 24)), cv2.FONT_HERSHEY_SIMPLEX, hfs,
                (0, 0, 0), int(hfs * 6), cv2.LINE_AA)
    cv2.putText(vis, hdr, (24, int(30 + hfs * 24)), cv2.FONT_HERSHEY_SIMPLEX, hfs,
                (0, 255, 255), max(2, int(hfs * 2)), cv2.LINE_AA)
    if not result.get("complete", False):
        warn = "INCOMPLETE: only {} of {} holes detected".format(
            result.get("detections", 0), result.get("expected", EXPECTED_HOLES))
        y2 = int(30 + hfs * 24 + hfs * 46)
        cv2.putText(vis, warn, (24, y2), cv2.FONT_HERSHEY_SIMPLEX, hfs, (0, 0, 0),
                    int(hfs * 6), cv2.LINE_AA)
        cv2.putText(vis, warn, (24, y2), cv2.FONT_HERSHEY_SIMPLEX, hfs, (0, 0, 255),
                    max(2, int(hfs * 2)), cv2.LINE_AA)
    return vis
