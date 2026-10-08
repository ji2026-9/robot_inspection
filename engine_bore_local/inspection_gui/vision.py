"""Qt shell adapter for the existing, independently validated detector.

This module only changes the result contract.  Recognition, part constraints,
rotation recovery, glare handling and ellipse fitting stay in detect_core.
"""

from __future__ import annotations

import gc
import math
from pathlib import Path
import re
import sys
import threading
import time

import cv2
import numpy as np


BASE = Path(__file__).resolve().parents[1]
EXPECTED_HOLES = 4
ORIENTATION_STATUS = "uncertain"
ORIENTATION_METHOD = "original_image_axis_order"
ORIENTATION_NOTE = "按当前原图位置编号；不是固定物理孔号。像素圆心尚未转换为三维或机械臂坐标。"


def imread_unicode(path):
    """Read BGR pixels from a Windows Unicode path, returning None on failure."""
    try:
        buffer = np.fromfile(str(path), dtype=np.uint8)
        if not buffer.size:
            return None
        return cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    except (OSError, ValueError, cv2.error):
        return None


def imwrite_unicode(path, image_bgr, quality=92):
    """Write BGR pixels without depending on cv2's Windows path handling."""
    try:
        destination = Path(path)
        extension = destination.suffix.lower() or ".jpg"
        options = [cv2.IMWRITE_JPEG_QUALITY, int(quality)] if extension in (".jpg", ".jpeg") else []
        ok, buffer = cv2.imencode(extension, image_bgr, options)
        if not ok:
            return False
        buffer.tofile(str(destination))
        return True
    except (OSError, ValueError, TypeError, cv2.error):
        return False


def _empty_result(image_path):
    return {
        "image_path": str(image_path) if image_path is not None else "",
        "image_size": None,
        "expected": EXPECTED_HOLES,
        "detections": 0,
        "center_count": 0,
        "reliable_center_count": 0,
        "complete": False,
        "holes": [],
        "fitted_holes": [],
        "detected_holes": [],
        "avg_conf": None,
        "part_confidence": None,
        "part_constraint_applied": False,
        "orientation_status": ORIENTATION_STATUS,
        "orientation_method": ORIENTATION_METHOD,
        "orientation_note": ORIENTATION_NOTE,
        "coordinate_frame": "image_pixel",
        "center_3d": None,
        "robot_ready": False,
        "warnings": [],
        "errors": [],
        "device_used": None,
        "device_name": None,
        "elapsed_s": None,
        "raw_report": None,
        "report": None,
        "result_image": None,
    }


def _report_to_result(report, image_path=None):
    """Map stored fits without estimating a new center or reordering holes.

``holes`` is deliberately limited to reliable fits.  ``detected_holes`` keeps
recognition counts even if no reliable center exists; its center can be None.
``fitted_holes`` additionally exposes the core's review-required fits for the
display, never for automatic task creation.
    """
    result = _empty_result(image_path or report.get("image"))
    result.update({
        "image_size": report.get("image_size"),
        "raw_report": report,
        "report": report,
        "result_image": report.get("result_image"),
        "part_confidence": report.get("part_max_confidence"),
        "part_constraint_applied": bool(report.get("part_constraint_applied")),
        "warnings": list(report.get("warnings", [])),
        "errors": list(report.get("errors", [])),
        "device_name": report.get("device"),
        "model_path": report.get("model"),
        "part_model_path": report.get("part_model"),
    })
    review_ids = set()
    for warning in result["warnings"]:
        hit = re.search(r"孔\s*(\d+)\s*(?:分割轮廓不稳定|拟合质量不足)", str(warning))
        if hit:
            review_ids.add(int(hit.group(1)))

    selected = report.get("selected_bores", report.get("centers", []))
    detected = {}
    for item in selected:
        number = int(item["hole_id"])
        confidence = float(item["confidence"])
        # The core's production floor is fixed at 0.5.  Do not pad missing holes.
        if confidence < 0.5 or not math.isfinite(confidence):
            continue
        detected[number] = {
            "id": "H{:02d}".format(number),
            "hole_id": number,
            "confidence": confidence,
            "class_name": "bore",
            "box_xyxy": item.get("box_xyxy"),
            "center_px": None,
            "center_3d": None,
            "coordinate_frame": "image_pixel",
            "reliable_center": False,
            "status": "center_unavailable",
        }

    width, height = (result["image_size"] or [None, None])
    for center in report.get("centers", []):
        number = int(center["hole_id"])
        if number not in detected:
            continue
        try:
            cx, cy = float(center["center_x_px"]), float(center["center_y_px"])
            axis1 = float(center["ellipse_axis1_px"])
            axis2 = float(center["ellipse_axis2_px"])
            angle = float(center["ellipse_angle_deg"])
            values = (cx, cy, axis1, axis2, angle)
            if not all(math.isfinite(value) for value in values) or min(axis1, axis2) <= 0:
                raise ValueError("圆心或椭圆参数无效")
            if width is not None and not (0 <= cx < width and 0 <= cy < height):
                raise ValueError("圆心超出原图")
        except (KeyError, TypeError, ValueError) as exc:
            result["warnings"].append("孔 {} 的结果参数无效，未提供可用圆心：{}".format(number, exc))
            continue
        support = center.get("contour_support")
        edge_verified = center.get("fit_source") == "image_edge_verified"
        low_support = support is not None and float(support) < 0.85 and not edge_verified
        reliable = number not in review_ids and not low_support
        ellipse = {
            "center": [cx, cy],
            "width": axis1,
            "height": axis2,
            "angle": angle,
            "major": max(axis1, axis2),
            "minor": min(axis1, axis2),
            "aspect": min(axis1, axis2) / max(axis1, axis2),
        }
        hole = dict(detected[number])
        hole.update({
            "center_px": [cx, cy],
            "ellipse": ellipse,
            # Keep OpenCV axis/angle pairing exactly as the core fitted it.
            "ellipse_raw": ((cx, cy), (axis1, axis2), angle),
            "reliable_center": reliable,
            "status": "detected" if reliable else "review_required",
            "orientation_status": ORIENTATION_STATUS,
            "fit_source": center.get("fit_source"),
            "fit_median_residual_px": center.get("fit_median_residual_px"),
            "contour_support": support,
            "edge_support": center.get("edge_support"),
            "edge_angle_coverage": center.get("edge_angle_coverage"),
            "edge_center_spread_px": center.get("edge_center_spread_px"),
            "source_rotation_deg": center.get("source_rotation_deg", 0),
            "source_model": center.get("source_model", "own"),
            "_contour": None,
            "_mask": None,
        })
        detected[number].update({
            "center_px": [cx, cy],
            "reliable_center": reliable,
            "status": hole["status"],
        })
        result["fitted_holes"].append(hole)
        if reliable:
            result["holes"].append(hole)

    # Keep the original ids (including gaps when a fit failed), never PCA-sort.
    result["detected_holes"] = list(detected.values())
    result["detections"] = len(detected)
    result["center_count"] = len(result["fitted_holes"])
    result["reliable_center_count"] = len(result["holes"])
    result["complete"] = len(detected) == EXPECTED_HOLES and len(result["holes"]) == EXPECTED_HOLES
    if detected:
        result["avg_conf"] = round(sum(item["confidence"] for item in detected.values()) / len(detected), 4)
    else:
        result["warnings"].append("未检测到置信度不低于 0.5 的 bore。")
    if not result["complete"]:
        result["warnings"].append("已识别 {} 个孔，拟合 {} 个圆心，其中 {} 个可用；完整任务需要 4 个可靠圆心。".format(
            result["detections"], result["center_count"], result["reliable_center_count"]))
    return result


class HoleDetector:
    """Lazy adapter; active model selection stays entirely in EngineDetector."""

    def __init__(self, weights=None, output_dir=None):
        self.weights = None
        self.output_dir = Path(output_dir) if output_dir is not None else BASE / "results"
        self._detector = None
        self._lock = threading.RLock()
        self.device_used = None
        self.load_error = None
        # Older shells may supply their own default weight path.  It must never
        # select the friend's checkpoint in this integrated application.
        self._ignored_weights = weights

    def load(self):
        with self._lock:
            if self._detector is not None:
                return True
            try:
                if str(BASE) not in sys.path:
                    sys.path.insert(0, str(BASE))
                from detect_core import EngineDetector
                self._detector = EngineDetector()
                self.weights = self._detector.model_path
                self.device_used = self._detector.device
                self.load_error = None
                return True
            except Exception as exc:
                self._detector = None
                self.load_error = "当前模型加载失败：{}".format(exc)
                return False

    def release(self):
        """Release cached models before training or after an active-model update."""
        with self._lock:
            self._detector = None
            self.weights = None
            self.device_used = None
            self.load_error = None
            gc.collect()
            torch = sys.modules.get("torch")
            if torch is not None and torch.cuda.is_available():
                torch.cuda.empty_cache()

    def detect(self, image_path, conf=None, imgsz=None):
        """Return shell fields plus the unmodified original detector report."""
        result = _empty_result(image_path)
        started = time.perf_counter()
        try:
            path = Path(image_path) if image_path else None
            if path is None or not path.is_file():
                result["errors"].append("图片不存在或尚未选择：{}".format(image_path))
                return result
            image = imread_unicode(path)
            if image is None:
                result["errors"].append("图片读取失败：{}".format(path))
                return result
            result["image_size"] = [image.shape[1], image.shape[0]]
            with self._lock:
                if not self.load():
                    result["errors"].append(self.load_error or "模型加载失败")
                    return result
                report = self._detector.analyze(path, output_dir=self.output_dir)
                result = _report_to_result(report, path)
                result["device_used"] = self._detector.device
                if self._ignored_weights is not None:
                    result["warnings"].append("检测使用本机当前验证模型，界面配置的旧权重路径已忽略。")
                if conf is not None and float(conf) != 0.5:
                    result["warnings"].append("孔保留阈值固定为 0.5，使用当前检测核心设置。")
                if imgsz is not None and int(imgsz) != self._detector.imgsz:
                    result["warnings"].append("输入尺寸使用当前检测核心设置。")
                if self._detector.device == "cpu":
                    result["warnings"].append("当前使用 CPU 检测，处理速度会较慢。")
        except Exception as exc:
            result["errors"].append("检测失败：{}".format(exc))
            result["complete"] = False
        finally:
            result["elapsed_s"] = round(time.perf_counter() - started, 3)
        return result


def draw_result(image_bgr, result):
    """Use the core's original annotated image; never refit an ellipse here."""
    report = (result or {}).get("raw_report") or {}
    saved = (result or {}).get("result_image") or report.get("result_image")
    if saved:
        rendered = imread_unicode(saved)
        if rendered is not None:
            return rendered
    return image_bgr.copy() if image_bgr is not None else None
