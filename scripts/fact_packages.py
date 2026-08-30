"""Build auditable, source-only fact packages from a Yuntu run directory."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

try:
    from .rpa_io import write_json_atomically
except ImportError:  # pragma: no cover - direct script imports
    from rpa_io import write_json_atomically


SCHEMA_VERSION = 2
PACKAGE_NAMES = ("material_ranking", "audience", "script", "highlight_frames")
AGE_PATTERN = re.compile(r"^(?:\d{2}-\d{2}|\d+\+)$")
CROWD_GROUPS = {
    "genz",
    "小镇中老年",
    "小镇青年",
    "新锐白领",
    "精致妈妈",
    "资深中产",
    "都市蓝领",
    "都市银发",
}


class FactPackageError(ValueError):
    """Raised when a run cannot be converted into consistent fact packages."""


def _read_json(path: Path, label: str):
    try:
        with path.open(encoding="utf-8") as source:
            return json.load(source)
    except (OSError, json.JSONDecodeError) as exc:
        raise FactPackageError(f"unable to read {label}: {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _source_paths(root: Path, *, normalized: str, raw: str | None = None) -> dict:
    paths = {"normalized": normalized}
    if raw:
        paths["raw"] = raw
    return paths


def _detail_id(path: Path, detail: dict) -> str:
    value = detail.get("material_id")
    if value is None or str(value).strip() == "":
        raise FactPackageError(f"detail record is missing material_id: {path}")
    material_id = str(value).strip()
    if path.stem != material_id:
        raise FactPackageError(
            f"detail material_id conflicts with filename: {path.name} vs {material_id}"
        )
    return material_id


def _audience_dimension(tag: str) -> str:
    if AGE_PATTERN.fullmatch(tag):
        return "age"
    if tag in {"男", "女"}:
        return "gender"
    if tag in CROWD_GROUPS:
        return "crowd_group"
    return "unclassified"


def _load_details(root: Path) -> dict[str, dict]:
    directory = root / "normalized" / "detail-records"
    if not directory.exists():
        return {}
    if not directory.is_dir():
        raise FactPackageError(f"detail-records is not a directory: {directory}")
    details = {}
    for path in sorted(directory.glob("*.json")):
        detail = _read_json(path, "detail record")
        if not isinstance(detail, dict):
            raise FactPackageError(f"detail record must be an object: {path}")
        material_id = _detail_id(path, detail)
        if material_id in details:
            raise FactPackageError(f"duplicate detail material_id: {material_id}")
        details[material_id] = detail
    return details


def _load_highlights(root: Path) -> dict[str, dict]:
    path = root / "highlights-manifest.json"
    if not path.exists():
        return {}
    payload = _read_json(path, "highlights manifest")
    materials = payload.get("materials") if isinstance(payload, dict) else None
    if materials is None:
        raise FactPackageError("highlights manifest materials must be an array")
    if not isinstance(materials, list):
        raise FactPackageError("highlights manifest materials must be an array")
    result = {}
    for item in materials:
        if not isinstance(item, dict) or not str(item.get("material_id", "")).strip():
            raise FactPackageError("highlight material must contain material_id")
        material_id = str(item["material_id"]).strip()
        if material_id in result:
            raise FactPackageError(f"duplicate highlight material_id: {material_id}")
        result[material_id] = item
    return result


def _ranking_payload(root: Path, records: list[dict]) -> dict:
    ordered = []
    for record in sorted(records, key=lambda item: item.get("rank", 0)):
        item = dict(record)
        item.pop("people_tags", None)
        item["source_paths"] = _source_paths(
            root,
            normalized="normalized/list-records.json",
            raw="raw-csv/list.csv",
        )
        ordered.append(item)
    return {"schema_version": SCHEMA_VERSION, "records": ordered}


def _audience_payload(root: Path, records: list[dict]) -> dict:
    ordered = []
    for record in sorted(records, key=lambda item: item.get("rank", 0)):
        raw_tags = record.get("people_tags")
        if not isinstance(raw_tags, list):
            raw_tags = []
        tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
        observations = [
            {"tag": tag, "dimension": _audience_dimension(tag)} for tag in tags
        ]
        ordered.append({
            "material_id": record.get("material_id"),
            "rank": record.get("rank"),
            "observations": observations,
            "raw_people_tags": tags,
            "data_availability": record.get("data_availability", {}).get("people_tags", {}),
            "source_paths": _source_paths(
                root,
                normalized="normalized/list-records.json",
                raw="raw-csv/list.csv",
            ),
        })
    return {"schema_version": SCHEMA_VERSION, "records": ordered}


def _script_payload(root: Path, details: dict[str, dict]) -> dict:
    records = []
    for material_id in sorted(details):
        detail = details[material_id]
        availability = detail.get("data_availability", {})
        records.append({
            "material_id": material_id,
            "date_range": detail.get("date_range"),
            "script_text": detail.get("script_text", ""),
            "content_formula": detail.get("content_formula"),
            "script_segments": detail.get("script_segments", []),
            "data_availability": {
                key: availability.get(key, {"available": False, "missing_reason": "source_empty"})
                for key in ("script_text", "content_formula", "script_segments")
            },
            "source_paths": _source_paths(
                root,
                normalized=f"normalized/detail-records/{material_id}.json",
                raw=f"raw-csv/details/{material_id}.csv",
            ),
        })
    return {"schema_version": SCHEMA_VERSION, "records": records}


def _highlight_payload(root: Path, details: dict[str, dict], highlights: dict[str, dict]) -> dict:
    records = []
    for material_id in sorted(set(details) | set(highlights)):
        detail = details.get(material_id, {})
        manifest_item = highlights.get(material_id, {})
        frames = manifest_item.get("frames", [])
        if not isinstance(frames, list):
            raise FactPackageError(f"highlight frames must be an array: {material_id}")
        records.append({
            "material_id": material_id,
            "date_range": detail.get("date_range"),
            "trend_series": detail.get("trend_series", []),
            "high_points": detail.get("high_points", []),
            "loss_points": detail.get("loss_points", []),
            "frames": frames,
            "data_availability": detail.get("data_availability", {}),
            "source_paths": {
                "detail_normalized": f"normalized/detail-records/{material_id}.json",
                "detail_raw": f"raw-csv/details/{material_id}.csv",
                "manifest": "highlights-manifest.json",
            },
        })
    return {"schema_version": SCHEMA_VERSION, "records": records}


def _source_artifacts(root: Path, details: dict[str, dict]) -> list[dict]:
    candidates = [root / "normalized/list-records.json"]
    candidates.extend(root / "normalized/detail-records" / f"{mid}.json" for mid in sorted(details))
    candidates.append(root / "highlights-manifest.json")
    candidates.append(root / "run-summary.json")
    artifacts = []
    for path in candidates:
        if not path.is_file():
            continue
        artifacts.append({
            "path": _relative(path, root),
            "size_bytes": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return artifacts


def _manifest(root: Path, details: dict[str, dict], highlights: dict[str, dict], payloads: dict[str, dict]) -> dict:
    available_frames = sum(
        1
        for item in highlights.values()
        for frame in item.get("frames", [])
        if isinstance(frame, dict) and frame.get("available") is True
    )
    run_summary = root / "run-summary.json"
    run_id = None
    if run_summary.is_file():
        summary = _read_json(run_summary, "run summary")
        if isinstance(summary, dict):
            run_id = summary.get("runId") or summary.get("run_id")
    filenames = {
        "material_ranking": "material-ranking.json",
        "audience": "audience.json",
        "script": "script.json",
        "highlight_frames": "highlight-frames.json",
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "run_root": ".",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "classification": {"packages": list(PACKAGE_NAMES), "principle": "source_facts_only"},
        "coverage": {
            "ranking_records": len(payloads["material_ranking"]["records"]),
            "detail_records": len(details),
            "script_records": len(payloads["script"]["records"]),
            "highlight_materials": len(highlights),
            "available_highlight_frames": available_frames,
        },
        "packages": {
            name: {
                "path": f"facts/{filenames[name]}",
                "record_count": len(payloads[name]["records"]),
                "source_paths": {
                    "material_ranking": ["normalized/list-records.json", "raw-csv/list.csv"],
                    "audience": ["normalized/list-records.json", "raw-csv/list.csv"],
                    "script": ["normalized/detail-records/", "raw-csv/details/"],
                    "highlight_frames": ["normalized/detail-records/", "raw-csv/details/", "highlights-manifest.json"],
                }[name],
            }
            for name in PACKAGE_NAMES
        },
        "source_artifacts": _source_artifacts(root, details),
    }


def build_fact_packages(run_dir: str | Path, *, output_dir: str | Path | None = None) -> dict:
    """Read a Yuntu run and atomically write four auditable fact packages."""
    root = Path(run_dir)
    if not root.is_dir():
        raise FactPackageError(f"run directory does not exist: {root}")
    list_path = root / "normalized" / "list-records.json"
    if not list_path.is_file():
        raise FactPackageError(f"required normalized list is missing: {list_path}")
    records = _read_json(list_path, "normalized list")
    if not isinstance(records, list):
        raise FactPackageError("normalized list records must be an array")
    if any(not isinstance(record, dict) for record in records):
        raise FactPackageError("normalized list records must contain objects")
    details = _load_details(root)
    highlights = _load_highlights(root)
    payloads = {
        "material_ranking": _ranking_payload(root, records),
        "audience": _audience_payload(root, records),
        "script": _script_payload(root, details),
        "highlight_frames": _highlight_payload(root, details, highlights),
    }
    manifest = _manifest(root, details, highlights, payloads)
    destination = Path(output_dir) if output_dir is not None else root / "facts"
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        files = {
            "material_ranking": "material-ranking.json",
            "audience": "audience.json",
            "script": "script.json",
            "highlight_frames": "highlight-frames.json",
        }
        for name, filename in files.items():
            write_json_atomically(payloads[name], staging / filename)
            manifest["packages"][name]["sha256"] = _sha256(staging / filename)
        write_json_atomically(manifest, staging / "manifest.json")
        destination.mkdir(parents=True, exist_ok=True)
        for path in staging.iterdir():
            os.replace(path, destination / path.name)
    except Exception:
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return manifest
