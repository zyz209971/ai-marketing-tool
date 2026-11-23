"""Regenerate RELEASE_MANIFEST.json for the current tree.

Produces the same format as the 2026-11-18 snapshot manifest: git provenance
(branch, base commit vs main, dirty flag) plus a sha256 inventory of every
tracked file, skipping runtime-only patterns that never belong in a release.

Usage:
    python scripts/make_release_manifest.py            # rewrite RELEASE_MANIFEST.json
    python scripts/make_release_manifest.py --check    # verify tree matches manifest, exit 1 on drift
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "RELEASE_MANIFEST.json"
RUNTIME_PATTERNS = (
    ".git/", ".venv/", "venv/", "node_modules/", "__pycache__/", ".pytest_cache/",
    ".local-data/", "backend/.env", "backend/.env.local", "backend/.env.deploy",
    ".env.deploy", "backend/data/", "frontend/node_modules/", ".specify/memory/",
)


def run(*args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def tracked_files():
    # NUL-delimited output keeps spaces and non-ASCII paths unquoted. Plain
    # `git ls-files` may emit C-style quoted Chinese paths on Windows, which
    # pathlib then mistakes for a literal filename.
    raw = subprocess.check_output(("git", "ls-files", "-z"), cwd=ROOT)
    return [name for name in raw.decode("utf-8").split("\0") if name]


def inventory(files):
    out = {}
    for rel in sorted(files):
        if rel == "RELEASE_MANIFEST.json":
            continue
        if any(rel.startswith(p) or rel == p.rstrip("/") for p in RUNTIME_PATTERNS):
            continue
        data = (ROOT / rel).read_bytes()
        out[rel] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return out


def build():
    branch = run("git", "rev-parse", "--abbrev-ref", "HEAD")
    base = run("git", "merge-base", "HEAD", "origin/main") if run("git", "rev-parse", "--verify", "origin/main") else run("git", "rev-parse", "HEAD")
    dirty = bool(run("git", "status", "--porcelain"))
    return {
        "package": "BrandPilot source snapshot",
        "release_status": "candidate",
        "created": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "source_branch": branch,
        "base_commit": base,
        "contains_working_tree_changes": dirty,
        "excluded_runtime_patterns": list(RUNTIME_PATTERNS),
        "files": inventory(tracked_files()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify tree matches manifest")
    args = ap.parse_args()
    current = build()
    if args.check:
        existing = json.loads(MANIFEST.read_text(encoding="utf-8"))
        drift = [k for k in current["files"] if existing["files"].get(k, {}).get("sha256") != current["files"][k]["sha256"]]
        missing = sorted(set(existing["files"]) - set(current["files"]))
        extra = sorted(set(current["files"]) - set(existing["files"]))
        if drift or missing or extra:
            print(f"DRIFT changed={len(drift)} missing={len(missing)} extra={len(extra)}")
            print("changed:", drift[:5], "missing:", missing[:5], "extra:", extra[:5])
            sys.exit(1)
        print("manifest matches tree.")
        return
    MANIFEST.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"RELEASE_MANIFEST.json rewritten: {len(current['files'])} files, branch={current['source_branch']}, base={current['base_commit'][:12]}")


if __name__ == "__main__":
    main()
