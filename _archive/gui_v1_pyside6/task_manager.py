# -*- coding: utf-8 -*-
"""
Task manager: turns detection results into measurement tasks and stores runs.
============================================================================
Task structure (per spec):
    {"target_id": "H03", "center_px": [x, y], "status": "pending"}

Tasks are kept independent of the robot so that, later, a real robot only
needs the ``center_px`` (plus the reserved coordinate-conversion fields).
"""

import json
from datetime import datetime
from pathlib import Path

import cv2

from config import EXPECTED_HOLES, RESULTS_ROOT
from vision import imwrite_unicode


class TaskManager:
    def __init__(self):
        self.tasks = []
        self.last_result = None

    # ------------------------------------------------------------ creation
    def create_auto_tasks(self, result):
        """All four holes -> four pending tasks. Incomplete detection -> no tasks."""
        self.tasks = []
        if not result or not result.get("holes"):
            return {"ok": False, "message": "尚未检测或未检测到目标"}
        if not result.get("complete", False):
            return {"ok": False,
                    "message": "检测不完整，请重新采集图像或调整检测参数。"
                               "（已识别 {}/{}，未生成任务）".format(
                                   result.get("detections", 0), EXPECTED_HOLES)}
        for h in result["holes"]:
            self.tasks.append({"target_id": h["id"],
                               "center_px": list(h["center_px"]),
                               "confidence": h["confidence"],
                               "ellipse": h.get("ellipse"),
                               "status": "pending",
                               "simulated": None})
        return {"ok": True, "message": "AI检测完成，已生成{}个检测目标。".format(len(self.tasks)),
                "count": len(self.tasks)}

    def create_manual_task(self, result, target_id):
        """One target chosen by the user. Verifies it really exists in the result."""
        self.tasks = []
        if not result or not result.get("holes"):
            return {"ok": False, "message": "尚未检测，无法生成任务"}
        hit = next((h for h in result["holes"] if h["id"] == target_id), None)
        if hit is None:
            return {"ok": False,
                    "message": "当前图像中没有可靠定位到 {}。".format(target_id)}
        self.tasks.append({"target_id": hit["id"],
                           "center_px": list(hit["center_px"]),
                           "confidence": hit["confidence"],
                           "ellipse": hit.get("ellipse"),
                           "status": "pending",
                           "simulated": None})
        return {"ok": True,
                "message": "目标已定位：{}  中心 {}  置信度 {:.3f}".format(
                    hit["id"], tuple(hit["center_px"]), hit["confidence"]),
                "count": 1}

    def available_targets(self):
        ids = ["H01", "H02", "H03", "H04"]
        return ids

    # ----------------------------------------------------------- execution
    def mark_executed(self, robot, simulate=True):
        if not self.tasks:
            return {"ok": False, "message": "当前没有检测任务"}
        if not simulate:
            return {"ok": False, "message": "机器人未连接，无法执行真实检测"}
        results = robot.simulate_execute(self.tasks)
        for t, r in zip(self.tasks, results):
            t["status"] = r["status"]
            t["simulated"] = r.get("simulated", True)
        return {"ok": True, "message": "已生成机器人目标任务，等待真实机器人接口。"
                                       "（本次为模拟执行，未连接真实机器人）",
                "results": results}

    # -------------------------------------------------------------- saving
    def save_run(self, result, annotated_bgr, extra=None):
        """Save one run into results/gui_runs/<timestamp>/ (never overwrites)."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        outdir = Path(RESULTS_ROOT) / ts
        k = 1
        while outdir.exists():
            outdir = Path(RESULTS_ROOT) / "{}_{:02d}".format(ts, k)
            k += 1
        outdir.mkdir(parents=True, exist_ok=True)

        img_name = Path(result.get("image_path", "image")).name if result else "image"
        vis_path = outdir / ("{}_result.jpg".format(Path(img_name).stem))
        if annotated_bgr is not None:
            if not imwrite_unicode(vis_path, annotated_bgr, 92):
                vis_path = outdir / "result.jpg"
                imwrite_unicode(vis_path, annotated_bgr, 92)

        payload = {
            "run_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_image": result.get("image_path") if result else None,
            "result_image": str(vis_path) if annotated_bgr is not None else None,
            "expected": result.get("expected") if result else None,
            "detections": result.get("detections") if result else None,
            "complete": result.get("complete") if result else None,
            "avg_confidence": result.get("avg_conf") if result else None,
            "device_used": result.get("device_used") if result else None,
            "orientation_status": result.get("orientation_status") if result else None,
            "orientation_method": result.get("orientation_method") if result else None,
            "orientation_note": result.get("orientation_note") if result else None,
            "warnings": result.get("warnings", []) if result else [],
            "errors": result.get("errors", []) if result else [],
            "holes": [{k2: v for k2, v in h.items() if not k2.startswith("_")}
                      for h in (result.get("holes", []) if result else [])],
            "tasks": self.tasks,
        }
        if extra:
            payload.update(extra)
        (outdir / "detection.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return outdir, payload
