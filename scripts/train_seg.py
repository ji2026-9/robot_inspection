# -*- coding: utf-8 -*-
"""
YOLO11n-Seg 训练脚本（RTX 3050 Ti 4GB 专用）
--------------------------------------------
- 默认参数：epochs=100, imgsz=640, batch=2, workers=2, patience=20, device=0
- 如果显存不足（CUDA out of memory），会自动降低 batch / imgsz 重试，不需要人工排查：
      (batch=2, imgsz=640) -> (1,640) -> (2,512) -> (1,512) -> (1,416)
- 训练完成后自动把 weights/best.pt 复制到 E:\\robot_inspection\\weights\\best.pt
- 同时保留完整 runs 目录与训练日志

用法：
    E:\\robot_inspection\\.venv\\Scripts\\python.exe scripts\\train_seg.py
    # 冒烟测试（只跑 1 轮，验证流程是否通）：
    E:\\robot_inspection\\.venv\\Scripts\\python.exe scripts\\train_seg.py --epochs 1 --name smoke_test
"""

import argparse
import contextlib
import csv
import shutil
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

PROJ = Path(r"E:\robot_inspection")
DEFAULT_DATA = PROJ / "dataset" / "box_yolo" / "data.yaml"
RUNS_DIR = PROJ / "runs"
WEIGHTS_DIR = PROJ / "weights"
LOGS_DIR = PROJ / "logs"

# 显存不足时的自动降级顺序
ATTEMPTS = [(2, 640), (1, 640), (2, 512), (1, 512), (1, 416)]


class Logger:
    def __init__(self, path: Path):
        self.f = open(path, "a", encoding="utf-8")

    def __call__(self, msg: str = ""):
        line = "[{}] {}".format(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
        print(line, flush=True)
        self.f.write(line + "\n")
        self.f.flush()

    def close(self):
        self.f.close()


def is_oom(exc: BaseException) -> bool:
    if isinstance(exc, MemoryError):
        return True
    text = "{}: {}".format(type(exc).__name__, exc).lower()
    keys = ["out of memory", "cuda error", "cublas", "not enough memory",
            "cudnn_status_alloc_failed", "cuda out of memory"]
    return any(k in text for k in keys)


class _Tee:
    """把写入同时送到多个流（终端 + 日志文件）。"""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
            except Exception:
                pass
        return len(data)

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass

    def isatty(self):
        return False

    @property
    def encoding(self):
        return "utf-8"


@contextlib.contextmanager
def capture_native_yolo_log(path: Path):
    """捕获 YOLO 原生训练输出（进度条 + LOGGER 消息），同时写终端和日志文件。

    这样每次训练都会留下完整的原生日志，方便事后复查训练过程。
    """
    import logging

    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a", encoding="utf-8", errors="replace")
    old_out, old_err = sys.stdout, sys.stderr
    tee_out, tee_err = _Tee(old_out, f), _Tee(old_err, f)
    sys.stdout, sys.stderr = tee_out, tee_err

    rebound = []
    ul = logging.getLogger("ultralytics")
    for h in list(ul.handlers):
        if isinstance(h, logging.StreamHandler) and hasattr(h, "setStream"):
            try:
                h.setStream(tee_out)
                rebound.append(h)
            except Exception:
                pass
    try:
        yield
    finally:
        sys.stdout, sys.stderr = old_out, old_err
        for h in rebound:
            try:
                h.setStream(old_out)
            except Exception:
                pass
        try:
            f.flush()
        finally:
            f.close()


def unique_run_name(project_dir: Path, base: str) -> str:
    """保证每次训练使用独立的实验目录，绝不覆盖以前的实验。"""
    if not (project_dir / base).exists():
        return base
    for i in range(2, 1000):
        cand = "{}_exp{:02d}".format(base, i)
        if not (project_dir / cand).exists():
            return cand
    return "{}_exp{}".format(base, datetime.now().strftime("%H%M%S"))


def summarize_run(run_dir: Path):
    """从 results.csv 里算出 best epoch 与对应指标（用于训练结束摘要/报告）。"""
    csv_path = run_dir / "results.csv"
    if not csv_path.is_file():
        return None

    try:
        rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    except Exception:
        return None
    if not rows:
        return None

    def g(row, key):
        try:
            return float(row[key])
        except Exception:
            return 0.0

    kb, km = "metrics/mAP50-95(B)", "metrics/mAP50-95(M)"
    # Ultralytics 分割任务的适应度：0.1*box + 0.9*mask，best.pt 就是该最大值对应的轮次
    best = max(rows, key=lambda r: 0.1 * g(r, kb) + 0.9 * g(r, km))
    return {
        "epochs": len(rows),
        "best_epoch": int(float(best.get("epoch", 0))),
        "precision": g(best, "metrics/precision(M)"),
        "recall": g(best, "metrics/recall(M)"),
        "map50": g(best, "metrics/mAP50(M)"),
        "map5095": g(best, "metrics/mAP50-95(M)"),
        "precision_b": g(best, "metrics/precision(B)"),
        "recall_b": g(best, "metrics/recall(B)"),
        "map50_b": g(best, "metrics/mAP50(B)"),
        "map5095_b": g(best, "metrics/mAP50-95(B)"),
    }


def prepare_data_yaml(data_path: Path, log) -> Path:
    """Ultralytics 对 data.yaml 里的相对 path 解析依赖当前工作目录，容易出错。

    这里在原目录旁边生成一个 data_local.yaml，把 path 改成绝对路径后再训练，
    原始 data.yaml 不做任何修改。
    """
    try:
        import yaml
    except Exception:
        return data_path

    try:
        d = yaml.safe_load(data_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        log("[警告] 读取 data.yaml 失败，直接使用原文件：{}".format(exc))
        return data_path

    if not isinstance(d, dict):
        return data_path

    abs_root = data_path.parent.resolve()
    d["path"] = str(abs_root).replace("\\", "/")

    out = data_path.parent / "data_local.yaml"
    out.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    log("[数据] 已生成绝对路径配置：{}  (path={})".format(out, d["path"]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--data-as-is", action="store_true",
                    help="直接使用 --data 指定的 yaml（不再生成绝对路径副本），适合数据集目录必须保持只读的场景")
    ap.add_argument("--weights", default="yolo11n-seg.pt", help="预训练权重（首次会自动下载）")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--batch", type=int, default=2)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--patience", type=int, default=20)
    ap.add_argument("--device", default="0")
    ap.add_argument("--name", default=None, help="runs 下的实验名，默认自动生成时间戳")
    ap.add_argument("--seed", type=int, default=0, help="随机种子（默认 0，与 Ultralytics 默认一致）")
    ap.add_argument("--project", default=str(RUNS_DIR), help="实验输出根目录（默认 E:\\robot_inspection\\runs）")
    ap.add_argument("--weights-out", default=str(WEIGHTS_DIR),
                    help="best.pt/last.pt 的保存目录（默认 E:\\robot_inspection\\weights，不会覆盖其它实验）")
    ap.add_argument("--logs-out", default=str(LOGS_DIR),
                    help="日志输出目录（默认 E:\\robot_inspection\\logs）")
    ap.add_argument("--deterministic", type=int, default=1, help="是否启用确定性训练，1=启用(默认) 0=关闭")
    ap.add_argument("--no-fallback", action="store_true", help="禁用自动降 batch 逻辑")
    args = ap.parse_args()

    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    WEIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    project_dir = Path(args.project)
    project_dir.mkdir(parents=True, exist_ok=True)
    weights_out = Path(args.weights_out)
    weights_out.mkdir(parents=True, exist_ok=True)
    logs_out = Path(args.logs_out)
    logs_out.mkdir(parents=True, exist_ok=True)

    base_name = args.name or "box_yolo_yolo11n_seg_seed{}".format(args.seed)
    run_name = unique_run_name(project_dir, base_name)
    log = Logger(logs_out / "train_{}.log".format(run_name))
    native_log = logs_out / "{}_native.log".format(run_name)
    log("=" * 70)
    log("训练开始   run_name = {}".format(run_name))
    if run_name != base_name:
        log("           注意：{} 已存在，本次自动改用独立目录 {}（不覆盖旧实验）".format(base_name, run_name))
    log("data       = {}".format(args.data))
    log("weights    = {}".format(args.weights))
    log("epochs={} patience={} workers={} device={}".format(
        args.epochs, args.patience, args.workers, args.device))
    log("seed={} deterministic={} batch={} imgsz={}".format(
        args.seed, bool(args.deterministic), args.batch, args.imgsz))
    log("project={}  weights_out={}".format(project_dir, weights_out))
    log("=" * 70)

    # ---- 环境自检 --------------------------------------------------------
    try:
        import torch
        log("torch={}  cuda_available={}".format(torch.__version__, torch.cuda.is_available()))
        if torch.cuda.is_available():
            log("GPU = {}  VRAM = {:.2f} GB".format(
                torch.cuda.get_device_name(0),
                torch.cuda.get_device_properties(0).total_memory / 1024 ** 3))
        else:
            log("[警告] CUDA 不可用，将退回 CPU 训练（非常慢）")
    except Exception:
        log("[警告] torch 自检失败：\n" + traceback.format_exc())

    data_path = Path(args.data)
    if not data_path.is_file():
        log("[错误] 找不到数据集配置：{}".format(data_path))
        log("       请先把 box_yolo_dataset.zip 解压到 E:\\robot_inspection\\dataset\\ 下。")
        log.close()
        return 2

    if args.data_as_is:
        log("[数据] 直接使用原样 yaml（不生成副本）：{}".format(data_path))
    else:
        data_path = prepare_data_yaml(data_path, log)

    from ultralytics import YOLO

    # 第一次一定用用户指定的配置，显存不足时才按降级表回退
    if args.no_fallback:
        attempts = [(args.batch, args.imgsz)]
    else:
        attempts = [(args.batch, args.imgsz)]
        attempts += [(b, s) for (b, s) in ATTEMPTS
                     if b <= args.batch and s <= args.imgsz and (b, s) != (args.batch, args.imgsz)]

    last_exc = None
    log("原生训练输出同时写入：{}".format(native_log))
    with capture_native_yolo_log(native_log):
        for idx, (batch, imgsz) in enumerate(attempts, 1):
            log("")
            log("-" * 70)
            log("[尝试 {}/{}] batch={}  imgsz={}  device={}".format(idx, len(attempts), batch, imgsz, args.device))
            log("-" * 70)
            t0 = time.time()
            try:
                model = YOLO(args.weights)
                model.train(
                    data=str(data_path),
                    epochs=args.epochs,
                    imgsz=imgsz,
                    batch=batch,
                    device=args.device,
                    workers=args.workers,
                    patience=args.patience,
                    project=str(project_dir),
                    name=run_name,
                    exist_ok=True,
                    seed=args.seed,
                    deterministic=bool(args.deterministic),
                    pretrained=True,
                    cache=False,
                    plots=True,
                    val=True,
                    verbose=True,
                )
                log("训练成功完成，用时 {:.1f} 分钟".format((time.time() - t0) / 60))
                last_exc = None
                break
            except Exception as exc:
                last_exc = exc
                log("[失败] batch={} imgsz={} -> {}: {}".format(batch, imgsz, type(exc).__name__, exc))
                if is_oom(exc):
                    log("       判定为显存不足，自动降低配置后重试……")
                    try:
                        import torch
                        torch.cuda.empty_cache()
                    except Exception:
                        pass
                    continue
                log("       非显存问题，终止：\n" + traceback.format_exc())
                break

    if last_exc is not None:
        log("")
        log("[错误] 所有配置都失败了，训练未完成。")
        log.close()
        return 1

    # ---- 复制 best.pt / last.pt 到永久目录 --------------------------------
    run_dir = project_dir / run_name
    best_src = run_dir / "weights" / "best.pt"
    last_src = run_dir / "weights" / "last.pt"

    if best_src.is_file():
        shutil.copy2(best_src, weights_out / "best.pt")
        log("[保存] {}  ->  {}".format(best_src, weights_out / "best.pt"))
    else:
        log("[错误] 找不到 {}".format(best_src))

    if last_src.is_file():
        shutil.copy2(last_src, weights_out / "last.pt")
        log("[保存] {}  ->  {}".format(last_src, weights_out / "last.pt"))

    (weights_out / "best_source.txt").write_text(
        "来源 run 目录: {}\nseed: {}\nbatch: {}\nimgsz: {}\nepochs: {}\npatience: {}\n复制时间: {}\n".format(
            run_dir, args.seed, ATTEMPTS[0][0], args.imgsz, args.epochs, args.patience,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        encoding="utf-8",
    )

    # ---- 输出结果摘要 ----------------------------------------------------
    res_csv = run_dir / "results.csv"
    if res_csv.is_file():
        log("")
        log("--- results.csv 摘要（表头 + 最后 5 行）---")
        lines = res_csv.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        for ln in lines[:1] + lines[-5:]:
            log("   " + ln)

    # ---- 本次训练产出的可视化文件清单（供报告使用） ----------------------
    artifacts = [run_dir / n for n in
                 ("results.csv", "results.png", "labels.jpg",
                  "MaskPR_curve.png", "MaskF1_curve.png", "MaskP_curve.png", "MaskR_curve.png",
                  "BoxPR_curve.png", "BoxF1_curve.png", "BoxP_curve.png", "BoxR_curve.png",
                  "confusion_matrix.png", "confusion_matrix_normalized.png",
                  "val_batch0_labels.jpg", "val_batch0_pred.jpg")]
    artifacts += sorted(run_dir.glob("train_batch*.jpg"))
    artifacts += sorted(run_dir.glob("val_batch*.jpg"))
    existing = [p for p in artifacts if p.is_file()]
    log("")
    log("--- 可视化产物（{} 个）---".format(len(existing)))
    for p in existing:
        log("   [有] {}".format(p.name))
    log("   [有] {}".format((run_dir / "weights" / "best.pt").name))
    log("   [有] {}".format((run_dir / "weights" / "last.pt").name))

    # ---- 训练结束摘要 ----------------------------------------------------
    s = summarize_run(run_dir)
    log("")
    log("========================================")
    log("TRAINING FINISHED")
    log("========================================")
    log("Best model:")
    log("{}".format(best_src if best_src.is_file() else "(未找到 best.pt)"))
    log("(已复制到永久位置: {})".format(weights_out / "best.pt"))
    if s:
        log("")
        log("Best epoch:")
        log("{}  (共训练 {} 轮)".format(s["best_epoch"], s["epochs"]))
        log("")
        log("mAP50:")
        log("{:.4f}  (Mask 分割；Box 检测 {:.4f})".format(s["map50"], s["map50_b"]))
        log("")
        log("mAP50-95:")
        log("{:.4f}  (Mask 分割；Box 检测 {:.4f})".format(s["map5095"], s["map5095_b"]))
        log("")
        log("Precision:")
        log("{:.4f}  (Mask 分割；Box 检测 {:.4f})".format(s["precision"], s["precision_b"]))
        log("")
        log("Recall:")
        log("{:.4f}  (Mask 分割；Box 检测 {:.4f})".format(s["recall"], s["recall_b"]))
    else:
        log("（未能从 results.csv 读取指标）")
    log("")
    log("实验目录 : {}".format(run_dir))
    log("权重目录 : {}".format(weights_out))
    log("原生日志 : {}".format(native_log))
    log("查看报告 : 运行 E:\\robot_inspection\\run_report.bat")
    log("========================================")

    log("")
    log("=" * 70)
    log("训练全部完成")
    log("  运行目录 : {}".format(run_dir))
    log("  权重输出 : {}".format(weights_out / "best.pt"))
    log("=" * 70)
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
