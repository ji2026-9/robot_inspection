# -*- coding: utf-8 -*-
"""
公开工业视觉数据集检索脚本
==========================
围绕「工业箱体 / 机械外壳 / 大型结构孔 / 通孔 / bore」等关键词，
在可达的公开平台上做真实检索，并把原始返回留档：

  Kaggle  : https://www.kaggle.com/api/v1/datasets/list
  GitHub  : https://api.github.com/search/repositories
  Zenodo  : https://zenodo.org/api/records

Hugging Face 在本机 DNS 不可达（实测 huggingface.co 解析失败），脚本会标记 SKIPPED_UNREACHABLE。

输出：
  external_datasets\\metadata\\raw\\*.json     原始返回
  external_datasets\\metadata\\search_hits.json  归一化后的检索命中

用法：
    python scripts\\search_public_datasets.py
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(r"E:\robot_inspection\external_datasets")
RAW = ROOT / "metadata" / "raw"
UA = {"User-Agent": "Mozilla/5.0 (research dataset audit)"}

KAGGLE_QUERIES = [
    "industrial box", "industrial housing", "machine housing", "industrial enclosure",
    "mechanical parts segmentation", "industrial parts segmentation", "hole detection",
    "through hole", "bore inspection", "metal surface defect", "industrial anomaly segmentation",
    "casting defect", "gearbox", "engine block", "bearing defect", "welding defect",
    "metal parts instance segmentation", "car parts segmentation", "machinery parts",
    "sheet metal", "industrial inspection", "robot vision industrial",
]

GITHUB_QUERIES = [
    "industrial dataset segmentation",
    "mechanical parts dataset",
    "hole detection dataset",
    "bore inspection",
    "machine housing segmentation",
    "industrial anomaly detection dataset",
    "defect segmentation dataset",
    "metal surface defect dataset",
    "robotic inspection dataset",
    "industrial object detection dataset",
]

ZENODO_QUERIES = [
    "industrial inspection dataset images",
    "metal component segmentation dataset",
    "hole inspection dataset",
    "mechanical part images dataset",
    "industrial machine parts dataset",
]


def get(url, timeout=40):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


def save_raw(name, obj):
    (RAW / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def search_kaggle(q):
    url = "https://www.kaggle.com/api/v1/datasets/list?search={}&page=1".format(
        urllib.parse.quote(q))
    st, body = get(url)
    data = json.loads(body)
    out = []
    for d in data:
        out.append({
            "platform": "Kaggle",
            "query": q,
            "title": d.get("title") or d.get("titleNullable"),
            "ref": d.get("ref"),
            "url": "https://www.kaggle.com/datasets/{}".format(d.get("ref")),
            "license": d.get("licenseName") or d.get("licenseNameNullable"),
            "totalBytes": d.get("totalBytes") or d.get("totalBytesNullable"),
            "downloadCount": d.get("downloadCount"),
            "voteCount": d.get("voteCount"),
            "lastUpdated": d.get("lastUpdated"),
            "subtitle": d.get("subtitle") or d.get("subtitleNullable"),
            "tags": d.get("tags"),
        })
    return out


def search_github(q):
    url = ("https://api.github.com/search/repositories?q={}"
           "&sort=stars&order=desc&per_page=10").format(urllib.parse.quote(q))
    st, body = get(url)
    data = json.loads(body)
    out = []
    for it in data.get("items", []):
        out.append({
            "platform": "GitHub",
            "query": q,
            "title": it.get("full_name"),
            "url": it.get("html_url"),
            "license": (it.get("license") or {}).get("spdx_id"),
            "stars": it.get("stargazers_count"),
            "description": it.get("description"),
            "updated_at": it.get("updated_at"),
            "topics": it.get("topics"),
        })
    return out, data.get("total_count")


def search_zenodo(q):
    url = ("https://zenodo.org/api/records?q={}&size=10&type=dataset"
           "&sort=mostrecent").format(urllib.parse.quote(q))
    st, body = get(url)
    data = json.loads(body)
    out = []
    for h in data.get("hits", {}).get("hits", []):
        md = h.get("metadata", {})
        lic = (md.get("license") or {})
        files = h.get("files", []) or []
        out.append({
            "platform": "Zenodo",
            "query": q,
            "title": md.get("title"),
            "url": h.get("links", {}).get("self_html") or h.get("doi_url"),
            "doi": h.get("doi"),
            "license": lic.get("id") or lic.get("title"),
            "files": [{"key": f.get("key"), "size": f.get("size")} for f in files][:10],
            "total_files_size": sum((f.get("size") or 0) for f in files),
            "publication_date": md.get("publication_date"),
            "description": (md.get("description") or "")[:400],
        })
    return out, data.get("hits", {}).get("total")


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    hits = []
    log = []

    # 可达性记录
    reach = {}
    for name, url in [("HuggingFace", "https://huggingface.co/api/datasets?limit=1"),
                      ("RoboflowUniverse", "https://universe.roboflow.com/search?q=industrial"),
                      ("PapersWithCode", "https://paperswithcode.com/api/v1/datasets/?q=hole")]:
        try:
            st, _ = get(url, timeout=20)
            reach[name] = "HTTP {}".format(st)
        except Exception as e:
            reach[name] = "SKIPPED_UNREACHABLE ({})".format(type(e).__name__)
    print("平台可达性:", json.dumps(reach, ensure_ascii=False))
    save_raw("platform_reachability.json", reach)

    for q in KAGGLE_QUERIES:
        try:
            res = search_kaggle(q)
            hits += res
            save_raw("kaggle_{}.json".format(q.replace(" ", "_")), res)
            print("Kaggle  {:<38} -> {}".format(q, len(res)))
        except Exception as e:
            log.append("Kaggle '{}' 失败: {}".format(q, e))
            print("Kaggle  {:<38} -> ERROR {}".format(q, e))
        time.sleep(1)

    for q in GITHUB_QUERIES:
        try:
            res, total = search_github(q)
            hits += res
            save_raw("github_{}.json".format(q.replace(" ", "_")), res)
            print("GitHub  {:<38} -> {} (总命中 {})".format(q, len(res), total))
        except Exception as e:
            log.append("GitHub '{}' 失败: {}".format(q, e))
            print("GitHub  {:<38} -> ERROR {}".format(q, e))
        time.sleep(3)

    for q in ZENODO_QUERIES:
        try:
            res, total = search_zenodo(q)
            hits += res
            save_raw("zenodo_{}.json".format(q.replace(" ", "_")), res)
            print("Zenodo  {:<38} -> {} (总命中 {})".format(q, len(res), total))
        except Exception as e:
            log.append("Zenodo '{}' 失败: {}".format(q, e))
            print("Zenodo  {:<38} -> ERROR {}".format(q, e))
        time.sleep(1)

    # 去重（按平台+URL）
    uniq = {}
    for h in hits:
        key = (h.get("platform"), h.get("url"))
        if key not in uniq:
            h["matched_queries"] = [h.get("query")]
            uniq[key] = h
        else:
            uniq[key]["matched_queries"].append(h.get("query"))
    uniq_list = list(uniq.values())

    out = {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "platform_reachability": reach,
           "total_raw_hits": len(hits),
           "unique_hits": len(uniq_list),
           "errors": log,
           "hits": uniq_list}
    (ROOT / "metadata" / "search_hits.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n原始命中 {} 条，去重后 {} 条".format(len(hits), len(uniq_list)))
    print("已保存: {}".format(ROOT / "metadata" / "search_hits.json"))
    if log:
        print("\n失败记录:")
        for l in log:
            print("  -", l)
    return 0


if __name__ == "__main__":
    sys.exit(main())
