# -*- coding: utf-8 -*-
"""
通用分块断点续传下载器（HTTP Range）
===================================
特性：
  - HEAD 探测：HTTP 状态 / Content-Length / Accept-Ranges
  - 30 秒测速 + ETA 估算；若 ETA > --max-hours 则拒绝开始
  - 服务器支持 Range 时：按 --chunk-mb 分块、--workers 并发、逐块断点续传
  - 每块下载后校验字节数；全部完成后拼接并做整体 SHA256
  - 失败时保留 <name>.part/ 目录（名字里明确带 .part），绝不留“半成品冒充成品”
  - 成功后写 manifest JSON：URL / 大小 / SHA256 / 下载时间 / HTTP 状态 / 是否完整 / License / 来源页

用法：
  python scripts\chunked_download.py --url <URL> --out <文件> --chunk-mb 8 --workers 4 \
         --license "CC BY 4.0" --source-page <来源页> --max-hours 2
"""

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0 (research dataset audit)"}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def head(url, timeout=30):
    req = urllib.request.Request(url, headers=UA, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return {"status": r.status,
                    "length": r.headers.get("Content-Length"),
                    "ranges": (r.headers.get("Accept-Ranges") or "").lower(),
                    "ctype": r.headers.get("Content-Type"),
                    "final_url": r.url}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "length": None, "ranges": "", "ctype": "", "final_url": url,
                "error": str(e)}
    except Exception as e:
        return {"status": "ERR", "length": None, "ranges": "", "ctype": "", "final_url": url,
                "error": "{}: {}".format(type(e).__name__, e)}


def speed_test(url, seconds=30, limit_mb=1):
    end = limit_mb * 1024 * 1024 - 1
    req = urllib.request.Request(url, headers=dict(UA, Range="bytes=0-{}".format(end)))
    t0 = time.time()
    got = 0
    try:
        with urllib.request.urlopen(req, timeout=60, context=CTX) as r:
            while time.time() - t0 < seconds:
                buf = r.read(262144)
                if not buf:
                    break
                got += len(buf)
    except Exception as e:
        return None, "{}: {}".format(type(e).__name__, e)
    dt = max(0.001, time.time() - t0)
    return got / dt, "{:.1f}s / {} bytes".format(dt, got)


def fetch_range(url, start, end, dest, attempts=5):
    """下载 [start,end]，带重试；返回写入字节数。"""
    want = end - start + 1
    for k in range(attempts):
        try:
            req = urllib.request.Request(url, headers=dict(
                UA, Range="bytes={}-{}".format(start, end)))
            with urllib.request.urlopen(req, timeout=120, context=CTX) as r, open(dest, "wb") as f:
                n = 0
                while True:
                    buf = r.read(262144)
                    if not buf:
                        break
                    f.write(buf)
                    n += len(buf)
            if n == want:
                return n
            time.sleep(2 + 2 * k)
        except Exception:
            time.sleep(2 + 2 * k)
    return -1


def sha256_file(p, buf=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(buf), b""):
            h.update(c)
    return h.hexdigest().upper()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--chunk-mb", type=int, default=8)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--max-hours", type=float, default=2.0)
    ap.add_argument("--license", default="未确认")
    ap.add_argument("--source-page", default="")
    ap.add_argument("--label", default="")
    args = ap.parse_args()

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    part_dir = out.with_name(out.name + ".part")
    manifest_path = out.with_name(out.name + ".manifest.json")

    print("=" * 74)
    print("URL :", args.url)
    print("OUT :", out)
    h = head(args.url)
    print("HEAD:", json.dumps(h, ensure_ascii=False))
    size = int(h["length"]) if (h["length"] and str(h["length"]).isdigit()) else None
    supports_range = "bytes" in (h["ranges"] or "")

    if size is None:
        print("[错误] 服务器未返回 Content-Length，无法做可靠分块下载，已停止（不做盲目整包下载）。")
        return 2

    print("文件大小: {:,} 字节 ({:.1f} MB)".format(size, size / 1024 / 1024))
    print("支持 Range:", supports_range, "| Accept-Ranges:", h["ranges"] or "(none)")

    sp, info = speed_test(args.url, seconds=30)
    if sp is None:
        print("[错误] 测速失败：", info)
        return 2
    eta_h = (size / sp) / 3600 if sp > 0 else 999
    print("实测速度: {:.0f} KB/s  ({})".format(sp / 1024, info))
    print("预计用时: {:.2f} 小时".format(eta_h))
    if eta_h > args.max_hours:
        print("[停止] 预计用时超过 {:.1f} 小时上限，按约定不开始下载。".format(args.max_hours))
        manifest_path.write_text(json.dumps({
            "url": args.url, "target": str(out), "http_status": h["status"],
            "content_length": size, "accept_ranges": h["ranges"],
            "measured_speed_kBs": round(sp / 1024, 1), "eta_hours": round(eta_h, 2),
            "complete": False, "reason": "eta_exceeds_limit",
            "license": args.license, "source_page": args.source_page,
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False, indent=2), encoding="utf-8")
        return 3

    if not supports_range:
        print("[信息] 服务器不支持 Range，改为单流下载一次。")
        try:
            req = urllib.request.Request(args.url, headers=UA)
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=120, context=CTX) as r, open(out, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            ok = out.stat().st_size == size
        except Exception as e:
            print("[错误] 下载失败：", e)
            return 2
        digest = sha256_file(out) if ok else ""
        manifest_path.write_text(json.dumps({
            "url": args.url, "target": str(out), "http_status": h["status"],
            "content_length": size, "bytes_on_disk": out.stat().st_size,
            "accept_ranges": h["ranges"], "measured_speed_kBs": round(sp / 1024, 1),
            "sha256": digest, "complete": bool(ok), "license": args.license,
            "source_page": args.source_page, "label": args.label,
            "downloaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False, indent=2), encoding="utf-8")
        print("完成:", ok, " SHA256:", digest)
        return 0 if ok else 1

    # ---------- 分块并发下载 ----------
    chunk = args.chunk_mb * 1024 * 1024
    n_chunks = (size + chunk - 1) // chunk
    part_dir.mkdir(parents=True, exist_ok=True)
    print("分块: {} 块 × {} MB, 并发 {}".format(n_chunks, args.chunk_mb, args.workers))

    jobs = []
    for i in range(n_chunks):
        s = i * chunk
        e = min(s + chunk, size) - 1
        jobs.append((i, s, e, part_dir / "chunk_{:05d}.bin".format(i)))

    todo = []
    done_bytes = 0
    for i, s, e, p in jobs:
        want = e - s + 1
        if p.is_file() and p.stat().st_size == want:
            done_bytes += want
        else:
            todo.append((i, s, e, p))
    print("已完成 {}/{} 块（{} MB），待下载 {} 块".format(
        n_chunks - len(todo), n_chunks, done_bytes // 1024 // 1024, len(todo)))

    t0 = time.time()
    failed = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_range, args.url, s, e, p): (i, s, e, p) for i, s, e, p in todo}
        done = 0
        for fut in cf.as_completed(futs):
            i, s, e, p = futs[fut]
            n = fut.result()
            done += 1
            if n < 0:
                failed.append(i)
                print("  [失败] chunk {:05d}".format(i), flush=True)
            else:
                print("  [OK  ] chunk {:05d}  {:.1f} MB   ({}/{})  已用 {:.0f}s".format(
                    i, n / 1024 / 1024, done, len(todo), time.time() - t0), flush=True)

    if failed:
        print("\n[中断] {} 块失败：{}".format(len(failed), failed[:20]))
        print("已保留断点目录（名字含 .part，审计阶段不得读取）：", part_dir)
        manifest_path.write_text(json.dumps({
            "url": args.url, "target": str(out), "content_length": size,
            "accept_ranges": h["ranges"], "complete": False,
            "failed_chunks": failed, "part_dir": str(part_dir),
            "license": args.license, "source_page": args.source_page,
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            ensure_ascii=False, indent=2), encoding="utf-8")
        return 1

    # ---------- 拼接 ----------
    tmp = out.with_name(out.name + ".part.assembling")
    with open(tmp, "wb") as fo:
        for i, s, e, p in jobs:
            with open(p, "rb") as fi:
                shutil.copyfileobj(fi, fo, 1 << 20)
    os.replace(tmp, out)
    ok = out.stat().st_size == size
    digest = sha256_file(out)
    print("\n拼接完成: {:,} 字节  大小正确={}".format(out.stat().st_size, ok))
    print("SHA256:", digest)

    if ok:
        shutil.rmtree(part_dir, ignore_errors=True)
        print("已删除分块目录")
    manifest_path.write_text(json.dumps({
        "url": args.url, "target": str(out), "http_status": h["status"],
        "content_length": size, "bytes_on_disk": out.stat().st_size,
        "accept_ranges": h["ranges"], "chunk_mb": args.chunk_mb, "workers": args.workers,
        "measured_speed_kBs": round(sp / 1024, 1), "sha256": digest, "complete": bool(ok),
        "license": args.license, "source_page": args.source_page, "label": args.label,
        "downloaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print("清单:", manifest_path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
