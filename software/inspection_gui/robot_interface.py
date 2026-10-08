# -*- coding: utf-8 -*-
"""
Robot interface layer.
======================
There is NO real robot in this build. Therefore:
  * ``is_connected()`` always returns False - we never pretend a robot is online;
  * real motion methods (``move_to_target`` / ``execute_measurement``) refuse to
    run and return an explicit error instead;
  * ``simulate_execute()`` performs a clearly-labelled SIMULATION so the whole
    workflow can still be demonstrated.

To support a real arm later, implement the same method names in a new class
and switch ``create_robot()`` - the GUI does not need to change.
"""

import time


class RobotBase:
    name = "base"

    def connect(self, *args, **kwargs):
        raise NotImplementedError

    def disconnect(self):
        raise NotImplementedError

    def is_connected(self) -> bool:
        raise NotImplementedError

    def move_to_target(self, target):
        raise NotImplementedError

    def execute_measurement(self, target):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


class MockRobot(RobotBase):
    """Explicitly-disconnected placeholder robot + labelled simulation."""

    name = "mock"

    def __init__(self):
        self._connected = False
        self._stopped = False
        self.log = []

    # ---- interface methods -------------------------------------------------
    def connect(self, *args, **kwargs):
        # Deliberately refuses: no hardware is present in this build.
        self.log.append("connect() 被调用，但当前版本没有真实机器人接口，拒绝连接")
        return False

    def disconnect(self):
        self._connected = False

    def is_connected(self) -> bool:
        return False

    def move_to_target(self, target):
        return {"ok": False,
                "reason": "机器人未连接：当前版本只有模拟接口，未执行任何真实运动",
                "target": target}

    def execute_measurement(self, target):
        return {"ok": False,
                "reason": "机器人未连接：当前版本只有模拟接口，未执行任何真实测量",
                "target": target}

    def stop(self):
        self._stopped = True

    # ---- clearly-labelled simulation --------------------------------------
    def simulate_execute(self, targets, delay=0.05):
        """Simulate moving to each target and measuring. Never claims success
        of a real robot; every entry is marked ``simulated=True``."""
        out = []
        for t in targets:
            if self._stopped:
                out.append({"target_id": t.get("target_id"), "status": "stopped",
                            "simulated": True})
                continue
            time.sleep(delay)
            out.append({"target_id": t.get("target_id"),
                        "center_px": t.get("center_px"),
                        "status": "simulated_done",
                        "simulated": True,
                        "message": "模拟完成（未连接真实机器人）"})
        self._stopped = False
        return out


def create_robot(mode="mock") -> RobotBase:
    """Factory: replace the body when a real robot driver becomes available."""
    return MockRobot()
