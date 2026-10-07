# -*- coding: utf-8 -*-
"""
模型置信度对比脚本
------------------
对指定权重在指定图片上跑推理，输出每张图片的所有检测置信度（低阈值，便于看清漏检/低分）。

用法：
    python scripts\\eval_confidences.py --weights <包根目录>\\weights\\best.pt
    python scripts\\eval_confidences.py --weights <对照模型> --tag seed42
"""

import argparse
import json
import sys
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[1] / "test_images"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", required=True)
    ap.add_argument("--images", default=str(DEFAULT_DIR), help="图片目录或单个文件")
    ap.add_argument("--conf-floor", type=float, default=0.05)
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--device", default="0")
    ap.add_argument("--tag", default=None, help="输出用标签，默认取权重所在目录名")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    w = Path(args.weights)
    if not w.is_file():
        print("[错误] 找不到权重：{}".format(w))
        return 2

    src = Path(args.images)
    if src.is_dir():
        images = sorted([p for p in src.iterdir() if p.suffix.lower() in IMG_EXTS])
    else:
        images = [src]
    if not images:
        print("[错误] 没有找到图片")
        return 2

    tag = args.tag or w.parent.name

    from ultralytics import YOLO
    model = YOLO(str(w))

    result = {"tag": tag, "weights": str(w), "conf_floor": args.conf_floor, "images": []}

    print("=" * 74)
    print("权重 : {}".format(w))
    print("标签 : {}   图片数: {}".format(tag, len(images)))
    print("=" * 74)

    for p in images:
        r = model.predict(source=str(p), conf=args.conf_floor, iou=0.7, imgsz=args.imgsz,
                          device=args.device, retina_masks=True, verbose=False)[0]
        n = 0 if r.masks is None else len(r.masks)
        confs = sorted([float(c) for c in r.boxes.conf.cpu().numpy()], reverse=True) if n else []
        print("{:<12} 检出 {:>2} 个   全部置信度: {}".format(
            p.name, len(confs), [round(c, 4) for c in confs]))
        result["images"].append({"image": p.name, "n_detections": len(confs),
                                 "confidences": [round(c, 4) for c in confs]})

    print("=" * 74)
    out = Path(args.json_out) if args.json_out else (w.parent / "confidences_{}.json".format(tag))
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已保存：{}".format(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
