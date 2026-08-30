#!/usr/bin/env python3
"""Check that the installed Yuntu runtime copy matches the source scripts."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


RUNTIME_FILES = (
    "scripts/collector.py",
    "scripts/brand_classifier.py",
    "scripts/fact_packages.py",
    "scripts/analysis_spec.py",
    "scripts/analysis_facts.py",
    "scripts/analysis_prompt.py",
    "scripts/analysis_result.py",
    "scripts/analysis_report.py",
    "scripts/model_analysis_request.py",
)


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_info(source_root, target_root, relative_path):
    source_path = source_root / relative_path
    target_path = target_root / relative_path
    source_sha = _sha256(source_path) if source_path.is_file() else None
    target_sha = _sha256(target_path) if target_path.is_file() else None
    return {
        "source_sha256": source_sha,
        "target_sha256": target_sha,
        "match": source_sha is not None and source_sha == target_sha,
    }


def _target_help(target_root):
    collector = target_root / "scripts" / "collector.py"
    if not collector.is_file():
        return False, "target collector.py is missing"
    try:
        completed = subprocess.run(
            [sys.executable, str(collector), "--help"],
            cwd=str(target_root),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"unable to run target collector --help: {exc}"
    if completed.returncode != 0:
        return False, f"target collector --help exited {completed.returncode}"
    if "build-facts" not in completed.stdout:
        return False, "target collector --help does not contain build-facts"
    return True, None


def check_runtime_sync(source_root, target_root):
    """Return structured, read-only source/target runtime synchronization status."""
    source_root = Path(source_root).resolve()
    target_root = Path(target_root).resolve()
    files = {
        relative_path: _file_info(source_root, target_root, relative_path)
        for relative_path in RUNTIME_FILES
    }
    mismatches = [
        relative_path for relative_path, info in files.items() if not info["match"]
    ]
    help_contains_build_facts, help_error = _target_help(target_root)
    if not help_contains_build_facts:
        mismatches.append("target collector --help")
    return {
        "ok": not mismatches,
        "source_root": str(source_root),
        "target_root": str(target_root),
        "files": files,
        "help_contains_build_facts": help_contains_build_facts,
        "mismatches": mismatches,
        "help_error": help_error,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parents[1]),
        help="source repository root (defaults to this checkout)",
    )
    parser.add_argument("--target", required=True, help="installed runtime copy root")
    args = parser.parse_args(argv)
    result = check_runtime_sync(args.source, args.target)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
