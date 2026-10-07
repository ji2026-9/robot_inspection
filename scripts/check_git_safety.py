# -*- coding: utf-8 -*-
"""
Git safety check for the robot_inspection project.

Purpose
-------
Make sure that no model weights and no large data ever enter Git.
Run this BEFORE every `git commit`:

    E:\\robot_inspection\\.venv\\Scripts\\python.exe E:\\robot_inspection\\scripts\\check_git_safety.py

It inspects BOTH:
  * files already tracked by Git   (git ls-files)
  * files currently staged         (git diff --cached --name-only)

Exit code 0 = safe, 1 = something must be fixed, 2 = cannot check.

This script is READ ONLY: it never modifies the repository.
It does NOT touch the model, the dataset or any image.
"""

import subprocess
import sys
from pathlib import Path

try:  # keep Chinese/odd file names from crashing a GBK console
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]          # E:\robot_inspection

MODEL_EXTS = (".pt", ".pth", ".onnx", ".engine", ".weights", ".h5", ".tflite")
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
ARCHIVE_EXTS = (".zip", ".7z", ".rar", ".tar", ".gz")

LARGE_MB = 5.0                                       # warn above this size


# --------------------------------------------------------------------------
def run_git(args):
    """Run a git command inside the project. Returns (ok, lines)."""
    try:
        p = subprocess.run(["git", "-c", "core.quotepath=false", "-C", str(ROOT)] + args,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None, ["git executable not found"]
    if p.returncode != 0:
        msg = (p.stderr or p.stdout or "").strip().splitlines()
        return False, msg or ["git exited with code {}".format(p.returncode)]
    return True, [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]


def kind_of(rel: str):
    """Classify a repo-relative path (forward slashes)."""
    low = rel.lower()
    parts = [p.lower() for p in rel.split("/")]
    name = parts[-1]

    hits = []
    if low.endswith(MODEL_EXTS):
        hits.append("MODEL FILES TRACKED")
    if low.endswith(ARCHIVE_EXTS):
        hits.append("ARCHIVES TRACKED")
    if "dataset" in parts:
        hits.append("DATASET TRACKED")
    if "external_datasets" in parts:
        hits.append("EXTERNAL DATA TRACKED")
    if "test_images" in parts:
        hits.append("TEST IMAGES TRACKED")
    if "runs" in parts:
        hits.append("RUNS TRACKED")
    if "friend_transfer" in parts:
        hits.append("TRANSFER PACKAGE TRACKED")
    if ".venv" in parts or "venv" in parts or "_installers" in parts:
        hits.append("ENVIRONMENT FILES TRACKED")
    if name.endswith((".pyc", ".pyo")):
        hits.append("PYC CACHE TRACKED")
    if "weights" in parts and low.endswith(MODEL_EXTS):
        pass                                     # already reported as model
    if name.endswith(IMAGE_EXTS) and (parts[0] in ("experiments", "results", "app")):
        hits.append("GENERATED IMAGES TRACKED")
    return hits


def main() -> int:
    print("GIT SAFETY CHECK")
    print("project:", ROOT)
    print()

    ok, lines = run_git(["rev-parse", "--is-inside-work-tree"])
    if ok is None:
        print("RESULT: CANNOT CHECK - {}".format(lines[0]))
        return 2
    if not ok or (lines and lines[0].lower() != "true"):
        print("RESULT: CANNOT CHECK - this folder is not a Git repository yet")
        print("        (run `git init` inside {} first)".format(ROOT))
        return 2

    ok, tracked = run_git(["ls-files"])
    if not ok:
        print("RESULT: CANNOT CHECK - git ls-files failed")
        for ln in tracked:
            print("   ", ln)
        return 2

    ok, staged = run_git(["diff", "--cached", "--name-only", "--diff-filter=ACMR"])
    if not ok:
        staged = []

    all_files = sorted(set(tracked) | set(staged))
    staged_set = set(staged)

    problems = {}
    for rel in all_files:
        for k in kind_of(rel):
            problems.setdefault(k, []).append(rel)

    # size check on tracked files (5 MB threshold)
    big = []
    for rel in tracked:
        p = ROOT / rel
        try:
            if p.is_file() and p.stat().st_size > LARGE_MB * 1024 * 1024:
                big.append((rel, p.stat().st_size / 1024 / 1024))
        except OSError:
            pass
    if big:
        problems["LARGE FILES TRACKED"] = ["{} ({:.1f} MB)".format(r, s) for r, s in big]

    checks = [
        "MODEL FILES TRACKED",
        "DATASET TRACKED",
        "EXTERNAL DATA TRACKED",
        "TEST IMAGES TRACKED",
        "RUNS TRACKED",
        "TRANSFER PACKAGE TRACKED",
        "ENVIRONMENT FILES TRACKED",
        "PYC CACHE TRACKED",
        "GENERATED IMAGES TRACKED",
        "ARCHIVES TRACKED",
        "LARGE FILES TRACKED",
    ]

    print("tracked files : {}".format(len(tracked)))
    if staged_set:
        print("staged files  : {}".format(len(staged_set)))
    print()

    failed = []
    for name in checks:
        hits = problems.get(name, [])
        status = "FAIL" if hits else "PASS"
        if hits:
            failed.append(name)
        print("{:<26}{}".format(name + ":", status))
        for rel in hits[:8]:
            mark = " [staged]" if rel in staged_set else ""
            print("      - {}{}".format(rel, mark))
        if len(hits) > 8:
            print("      ... and {} more".format(len(hits) - 8))

    # informational: what is currently untracked but NOT ignored
    ok, others = run_git(["status", "--porcelain", "--untracked-files=all"])
    if ok:
        untracked = [ln[3:] for ln in others if ln.startswith("?? ")]
        if untracked:
            print()
            print("NOTE: {} untracked file(s) are not ignored (they are candidates for a future commit)."
                  .format(len(untracked)))
            for rel in untracked[:10]:
                print("      + {}".format(rel))
            if len(untracked) > 10:
                print("      ... and {} more".format(len(untracked) - 10))

    print()
    if failed:
        print("RESULT: FAIL - {} problem group(s): {}".format(len(failed), ", ".join(failed)))
        print("        Fix .gitignore (or unstage the files) BEFORE committing.")
        return 1
    print("RESULT: PASS - no model / no dataset / no large file is tracked or staged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
