# -*- coding: utf-8 -*-
"""
检测结果总览报告生成脚本
------------------------
读取 E:\\robot_inspection\\results\\detection_report.json 与结果图片，生成 HTML 总览报告。

【只读脚本】不重新推理、不修改检测算法、不修改 best.pt，只新增一个 HTML 文件。

用法：
    python scripts\\make_detection_report.py
    python scripts\\make_detection_report.py --out E:\\robot_inspection\\results\\detection_report.html
"""

import argparse
import hashlib
import html
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJ = Path(r"E:\robot_inspection")
RESULTS_DIR = PROJ / "results"
TEST_DIR = PROJ / "test_images"
DATASET_TEST_DIR = PROJ / "dataset" / "box_yolo" / "images" / "test"
WEIGHTS = PROJ / "weights" / "best.pt"
JSON_PATH = RESULTS_DIR / "detection_report.json"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
LOW_THRESHOLD = 0.50


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def rel_src(p: Path, base: Path) -> str:
    try:
        return os.path.relpath(str(p), str(base)).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def find_image(stem: str):
    """在 test_images / dataset test 目录里找原图。"""
    for d in (TEST_DIR, DATASET_TEST_DIR):
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if p.stem == stem and p.suffix.lower() in IMG_EXTS:
                return p
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(JSON_PATH))
    ap.add_argument("--out", default=str(RESULTS_DIR / "detection_report.html"))
    ap.add_argument("--conf", type=float, default=LOW_THRESHOLD)
    args = ap.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = Path(args.json)

    if not json_path.is_file():
        print("[错误] 找不到检测结果 JSON：{}".format(json_path))
        print("       请先运行 run_test.bat（scripts\\predict_holes.py）生成检测结果，再来生成报告。")
        return 2

    data = json.loads(json_path.read_text(encoding="utf-8"))
    images = data.get("images", [])
    conf_thr = float(data.get("conf_threshold", args.conf))

    # 汇总统计
    n_img = len(images)
    n_ok4 = sum(1 for e in images if e.get("detections") == 4)
    total_holes = sum(len(e.get("holes", [])) for e in images)
    low_list = []
    for e in images:
        stem = Path(e["image"]).stem
        for h in e.get("holes", []):
            if float(h.get("confidence", 0)) < conf_thr:
                low_list.append((stem, h["id"], float(h["confidence"])))

    # 模型文件信息
    model_info = "未找到 weights\\best.pt"
    if WEIGHTS.is_file():
        st = WEIGHTS.stat()
        model_info = "{}　|　{:,} 字节 ({:.2f} MB)　|　修改时间 {}　|　SHA256 {}…".format(
            str(WEIGHTS), st.st_size, st.st_size / 1024 ** 2,
            datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            sha256_file(WEIGHTS)[:16])

    css = """
    :root{--bg:#f5f7fa;--card:#fff;--line:#e2e8f0;--txt:#1f2937;--muted:#6b7280;
          --blue:#2563eb;--green:#16a34a;--amber:#d97706;--red:#dc2626;}
    *{box-sizing:border-box}
    body{margin:0;padding:28px;background:var(--bg);color:var(--txt);
         font-family:"Segoe UI","Microsoft YaHei",system-ui,sans-serif;line-height:1.6}
    h1{font-size:26px;margin:0 0 6px}
    h2{font-size:19px;margin:34px 0 14px;padding-left:10px;border-left:5px solid var(--blue)}
    .sub{color:var(--muted);font-size:13px;margin-bottom:20px;word-break:break-all}
    .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;
           padding:18px 20px;margin-bottom:18px;box-shadow:0 1px 2px rgba(0,0,0,.04)}
    table{border-collapse:collapse;width:100%;font-size:14px}
    th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:middle}
    th{background:#eef2f7;font-weight:600;white-space:nowrap}
    td.num{font-variant-numeric:tabular-nums}
    .kpi{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
    .kpi div{background:#eef6ff;border:1px solid #dbeafe;border-radius:10px;padding:12px 14px}
    .kpi b{display:block;font-size:22px;color:var(--blue);font-variant-numeric:tabular-nums}
    .kpi span{font-size:12px;color:var(--muted)}
    .pair{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
    .pair figure{margin:0;background:var(--card);border:1px solid var(--line);
                 border-radius:12px;padding:10px}
    .pair img{width:100%;height:auto;border-radius:8px;display:block;border:1px solid var(--line)}
    .pair figcaption{font-size:12px;color:var(--muted);margin-top:6px}
    .bar{position:relative;height:18px;background:#eef2f7;border-radius:9px;overflow:hidden;min-width:120px}
    .bar i{position:absolute;left:0;top:0;bottom:0;border-radius:9px;display:block}
    .bar span{position:relative;z-index:1;font-size:12px;line-height:18px;padding-left:8px;
              font-weight:600;font-variant-numeric:tabular-nums}
    .tag{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700}
    .ok{background:#dcfce7;color:#166534}
    .low{background:#fef3c7;color:#92400e}
    .red{background:#fee2e2;color:#991b1b}
    .legend span{display:inline-block;margin-right:18px;font-size:13px}
    .dot{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:5px;
         vertical-align:-1px;border:1px solid rgba(0,0,0,.15)}
    .warn{background:#fffbeb;border:1px solid #fde68a;border-radius:10px;padding:12px 14px;
          font-size:13px;color:#92400e;margin-bottom:16px}
    .mono{font-family:Consolas,monospace;font-size:12px}
    """

    P = []
    A = P.append
    A("<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'>")
    A("<title>检测结果总览报告</title><style>{}</style></head><body>".format(css))
    A("<h1>YOLO-Seg 孔位检测结果总览</h1>")
    A("<div class='sub'>模型权重：{}<br>置信度阈值：{}　|　报告生成时间：{}"
      "<br>数据来源：{}</div>".format(
          html.escape(model_info), conf_thr,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
          html.escape(str(json_path))))

    if low_list:
        A("<div class='warn'><b>注意：本次检测存在低置信度结果</b>（confidence &lt; {}）。"
          "下方表格中以 <span class='tag low'>LOW CONFIDENCE</span> 明确标出，未伪装成正常结果。<br>"
          "涉及：{}</div>".format(
              conf_thr,
              "、".join("{} {}".format(s, i) for s, i, _ in low_list)))

    A("<h2>总体结果</h2><div class='panel'><div class='kpi'>")
    A("<div><b>{}/{}</b><span>图片检出 4 个孔</span></div>".format(n_ok4, n_img))
    A("<div><b>{}</b><span>有效孔总数</span></div>".format(total_holes))
    A("<div><b>{}</b><span>低置信度孔数</span></div>".format(len(low_list)))
    A("<div><b>{}</b><span>置信度阈值</span></div>".format(conf_thr))
    A("</div></div>")

    A("<h2>可视化图例（与 predict_holes.py 实际输出一致）</h2><div class='panel legend'>")
    A("<span><i class='dot' style='background:#ffffff'></i>白色线 = YOLO 分割 mask 轮廓</span>")
    A("<span><i class='dot' style='background:#00ff00'></i>绿色椭圆 = cv2.fitEllipse 拟合结果</span>")
    A("<span><i class='dot' style='background:#ff0000'></i>红色圆点 = 椭圆中心（孔中心）</span>")
    A("<span><i class='dot' style='background:#0000ff'></i>蓝色直线 = PCA 工件长轴</span>")
    A("<span><i class='dot' style='background:#ffc800'></i>彩色半透明区域 = 各孔 mask</span>")
    A("<span>标签 H01~H04 = 沿 PCA 主轴排序后的孔编号</span>")
    A("<p class='mono' style='color:#6b7280;margin:10px 0 0'>"
      "说明：以上颜色取自现有 predict_holes.py 的既有输出，本次未改动检测算法。"
      "（提示：当前实现里椭圆是绿色、PCA 轴是蓝色，与最初设想的“黄色椭圆 / 紫色主轴”不同；"
      "如需改成该配色，请告知，我可以只调整绘图配色后重跑一次推理。）</p>")
    A("</div>")

    for e in images:
        stem = Path(e["image"]).stem
        res_img = RESULTS_DIR / "{}_result.jpg".format(stem)
        org_img = find_image(stem)
        n_det = e.get("detections", 0)
        holes = e.get("holes", [])
        n_low_this = sum(1 for h in holes if float(h.get("confidence", 0)) < conf_thr)

        A("<h2>{}　<span class='tag {}'>检出 {} / 4 个孔{}</span></h2>".format(
            html.escape(stem), "ok" if n_det == 4 and n_low_this == 0 else "low",
            n_det, "" if n_low_this == 0 else "，其中 {} 个低置信度".format(n_low_this)))

        A("<div class='pair'>")
        for label, p in [("原始图片", org_img), ("检测 + 后处理结果", res_img)]:
            if p is not None and Path(p).is_file():
                A("<figure><a href='{}' target='_blank'><img src='{}' alt='{}'></a>"
                  "<figcaption>{}：{}</figcaption></figure>".format(
                      rel_src(Path(p), out_path.parent), rel_src(Path(p), out_path.parent),
                      html.escape(label), html.escape(label), html.escape(Path(p).name)))
            else:
                A("<figure><div style='padding:40px;text-align:center;color:#d97706'>"
                  "（未找到{}图片）</div><figcaption>{}</figcaption></figure>".format(
                      html.escape(label), html.escape(label)))
        A("</div>")

        A("<div class='panel'><table>")
        A("<tr><th>编号</th><th>confidence</th><th>置信度条</th>"
          "<th>椭圆中心 (x, y)</th><th>ellipse width</th><th>ellipse height</th>"
          "<th>ellipse angle</th><th>状态</th></tr>")
        for h in sorted(holes, key=lambda x: x["id"]):
            c = float(h.get("confidence", 0))
            low = c < conf_thr
            cx, cy = h.get("ellipse_center", [None, None])
            bar_color = "#dc2626" if c < 0.3 else ("#d97706" if low else "#16a34a")
            A("<tr><td><b>{}</b></td><td class='num'>{:.4f}</td>"
              "<td><div class='bar'><i style='width:{:.1f}%;background:{}'></i>"
              "<span>{:.2f}</span></div></td>"
              "<td class='num'>({:.1f}, {:.1f})</td>"
              "<td class='num'>{:.2f}</td><td class='num'>{:.2f}</td><td class='num'>{:.2f}</td>"
              "<td>{}</td></tr>".format(
                  html.escape(str(h["id"])), c, c * 100, bar_color, c,
                  float(cx) if cx is not None else 0.0,
                  float(cy) if cy is not None else 0.0,
                  float(h.get("ellipse_width", 0)), float(h.get("ellipse_height", 0)),
                  float(h.get("ellipse_angle_deg", 0)),
                  "<span class='tag low'>LOW CONFIDENCE</span>" if low
                  else "<span class='tag ok'>正常</span>"))
        A("</table>")
        A("<p class='mono' style='color:#6b7280;margin:10px 0 0'>"
          "class = {}　|　原图路径：{}　|　结果图：{}</p>".format(
              html.escape(str(holes[0].get("class", "cylinder_bore")) if holes else "-"),
              html.escape(str(e["image"])), html.escape(str(res_img))))
        A("</div>")

    A("</body></html>")
    out_path.write_text("\n".join(P), encoding="utf-8")

    print("[OK] 检测报告已生成：{}".format(out_path))
    print("     图片 {}/{} 张检出 4 个孔，孔总数 {}，低置信度 {} 个".format(
        n_ok4, n_img, total_holes, len(low_list)))
    for s, i, c in low_list:
        print("     [LOW] {} {}  confidence={:.4f}".format(s, i, c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
