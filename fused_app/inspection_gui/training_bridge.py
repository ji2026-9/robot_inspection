"""Launch the existing dataset tools without loading detection in this process."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess

from PySide6.QtCore import QObject, QTimer, Signal, Slot


BASE = Path(__file__).resolve().parents[1]
_TERMINAL_STAGES = {"complete", "rejected", "failed", "error", "stopped", "cancelled"}


class TrainingBridge(QObject):
    """One management child at a time, with an explicit lifetime busy signal.

    ``busy_changed(True)`` is emitted before launching the child, allowing the
    main window to release its detector first.  ``finished`` means the child
    has exited.  ``model_updated`` requests a refresh after a training terminal
    status or an active-model manifest change; it does not clear ``busy``.
    The child owns the decision to stop or keep its running training job.
    """

    busy_changed = Signal(bool)
    finished = Signal()
    model_updated = Signal()
    log = Signal(str)

    def __init__(self, parent: QObject | None = None, *, base: str | Path = BASE,
                 executable: str | Path | None = None):
        super().__init__(parent)
        self.base = Path(base).resolve()
        from runtime_paths import python_executable
        self.executable = Path(executable) if executable else python_executable(windowless=True)
        self._process: subprocess.Popen | None = None
        self._busy = False
        self._mode: str | None = None
        self._log_handle = None
        self.last_log_path: Path | None = None
        self._log_offset = 0
        self._observed_status: dict[Path, tuple[int, int]] = {}
        self._status_messages: dict[Path, str] = {}
        self._terminal_jobs: set[tuple[Path, str]] = set()
        self._manifest_signature = None
        self._timer = QTimer(self)
        self._timer.setInterval(700)
        self._timer.timeout.connect(self._poll)

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def mode(self) -> str | None:
        return self._mode

    @Slot()
    def open_dataset(self) -> bool:
        return self._launch("dataset")

    @Slot()
    def open_validation(self) -> bool:
        return self._launch("validation")

    def _launch(self, mode: str) -> bool:
        if self._process is not None and self._process.poll() is None:
            self.log.emit(
                "训练数据管理窗口已经打开，请返回该窗口操作。查看验证请点击其中的“查看训练前后验证结果”。"
                if self._mode == "dataset" else
                "验证结果窗口已经打开，请先关闭该窗口，再打开训练数据管理。"
            )
            return False
        if self._process is not None:
            self._poll()
        script = self.base / "app.py"
        if not self.executable.is_file() or not script.is_file():
            self.log.emit(f"管理窗口未能启动：缺少运行环境或程序文件。\n{self.executable}\n{script}")
            return False

        self._observed_status = self._status_signatures()
        self._status_messages.clear()
        self._terminal_jobs.clear()
        self._manifest_signature = self._signature(self.base / "active_models.json")
        self._log_offset = 0
        try:
            log_folder = self.base / "logs"
            log_folder.mkdir(parents=True, exist_ok=True)
            self.last_log_path = log_folder / f"management_{datetime.now():%Y%m%d_%H%M%S_%f}.log"
            self._log_handle = self.last_log_path.open("wb")
        except OSError as error:
            self.log.emit(f"管理窗口未能启动：无法保存运行日志。{error}")
            return False

        self._busy, self._mode = True, mode
        self.busy_changed.emit(True)
        environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        arguments = [str(self.executable), str(script), f"--{mode}-only"]
        try:
            self._process = subprocess.Popen(
                arguments, cwd=str(self.base), env=environment,
                stdin=subprocess.DEVNULL, stdout=self._log_handle,
                stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            self._close_log()
            self._process, self._mode, self._busy = None, None, False
            self.log.emit(f"管理窗口启动失败：{error}")
            self.busy_changed.emit(False)
            self.finished.emit()
            return False
        self.log.emit("已打开添加训练照片和自动更新窗口。管理期间暂停检测。" if mode == "dataset"
                      else "已打开训练验证结果窗口。关闭后可继续检测。")
        self._timer.start()
        return True

    @staticmethod
    def _signature(path: Path):
        try:
            stat = path.stat()
            return stat.st_mtime_ns, stat.st_size
        except OSError:
            return None

    def _status_signatures(self) -> dict[Path, tuple[int, int]]:
        signatures = {}
        for path in (self.base / "updates").glob("*/status.json"):
            signature = self._signature(path)
            if signature is not None:
                signatures[path] = signature
        return signatures

    def _read_management_log(self) -> None:
        if self.last_log_path is None:
            return
        try:
            with self.last_log_path.open("rb") as stream:
                stream.seek(self._log_offset)
                content = stream.read(65536)
                self._log_offset = stream.tell()
            if content:
                self.log.emit(content.decode("utf-8", errors="replace").rstrip())
        except OSError:
            pass

    @Slot()
    def _poll(self) -> None:
        if self._process is None:
            return
        self._read_management_log()
        refresh_needed = False
        for path, signature in self._status_signatures().items():
            if self._observed_status.get(path) == signature:
                continue
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # Retry an incomplete concurrent write on the next timer tick.
                continue
            self._observed_status[path] = signature
            message = str(state.get("message", ""))
            if message and self._status_messages.get(path) != message:
                self._status_messages[path] = message
                self.log.emit(message)
            stage = str(state.get("stage", ""))
            if stage in _TERMINAL_STAGES and (path, stage) not in self._terminal_jobs:
                self._terminal_jobs.add((path, stage))
                refresh_needed = True
        manifest_signature = self._signature(self.base / "active_models.json")
        if manifest_signature != self._manifest_signature:
            self._manifest_signature = manifest_signature
            refresh_needed = True
        if refresh_needed:
            self.model_updated.emit()

        exit_code = self._process.poll()
        if exit_code is None:
            return
        self._read_management_log()
        self._timer.stop()
        self._process, self._mode, self._busy = None, None, False
        self._close_log()
        self.log.emit("管理窗口已关闭，可以继续检测。" if exit_code == 0
                      else f"管理窗口异常退出（代码 {exit_code}），正式模型和实验记录保留。日志：{self.last_log_path}")
        self.busy_changed.emit(False)
        self.finished.emit()

    def _close_log(self) -> None:
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None

    def detach(self) -> None:
        """Stop monitoring when Qt closes; keep the independently owned tool alive."""
        self._timer.stop()
        self._close_log()
