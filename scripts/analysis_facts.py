"""Load selected, manifest-verified fact packages and expose stable references."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .analysis_spec import AnalysisSpec, validate_analysis_spec
except ImportError:  # pragma: no cover - direct collector execution
    from analysis_spec import AnalysisSpec, validate_analysis_spec


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as source:
        return json.load(source)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"manifest path escapes run root: {relative}") from exc
    return path


def _verify_source_artifacts(root: Path, manifest: dict) -> None:
    for artifact in manifest.get("source_artifacts", []):
        if not isinstance(artifact, dict):
            raise ValueError("manifest source_artifacts must contain objects")
        relative = artifact.get("path")
        expected = artifact.get("sha256")
        if not isinstance(relative, str) or not isinstance(expected, str):
            raise ValueError("manifest source artifact must contain path and sha256")
        path = _safe_path(root, relative)
        if not path.is_file():
            raise ValueError(f"manifest source artifact is missing: {relative}")
        actual = _sha256(path)
        if actual != expected:
            raise ValueError(f"manifest SHA-256 mismatch: {relative}")


def _selected_records(records: list[dict], spec: AnalysisSpec, section: str, ranking_ids: set[str]) -> list[dict]:
    start, end = spec.filters["rank_range"]
    material_ids = set(spec.filters["material_ids"])
    brand_filter = set(spec.filters.get("brand_filter", ()))
    result = []
    for original_index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"{section} package records must contain objects")
        record_material_id = str(record.get("material_id", ""))
        if material_ids and record_material_id not in material_ids:
            continue
        rank = record.get("rank")
        if isinstance(rank, int) and not start <= rank <= end:
            continue
        if not isinstance(rank, int) and ranking_ids and section in {"script", "highlight_frames"}:
            if record_material_id not in ranking_ids:
                continue
        if brand_filter and not _record_matches_brand(record, brand_filter):
            continue
        result.append((original_index, record))
    return result


def _record_matches_brand(record: dict, brand_filter: set[str]) -> bool:
    """Match only persisted classification snapshots; never reclassify facts."""

    classification = record.get("brand_classification")
    if not isinstance(classification, dict):
        return False
    matched = classification.get("matchedBrands")
    if isinstance(matched, list):
        matched_brands = {str(item) for item in matched}
    else:
        matched_brands = set()
    value = classification.get("value")
    if value == "未知品牌":
        matched_brands.add("未知品牌")
    elif isinstance(value, str) and value:
        matched_brands.add(value)
    elif isinstance(value, list):
        matched_brands.update(str(item) for item in value)
    return bool(matched_brands & brand_filter)


def load_selected_facts(run_root: Path, spec: AnalysisSpec) -> dict:
    root = Path(run_root)
    if not root.is_dir():
        raise ValueError(f"run directory does not exist: {root}")
    manifest_path = root / "facts" / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"facts manifest is missing: {manifest_path}")
    manifest = _read_json(manifest_path)
    errors = validate_analysis_spec(spec, manifest)
    if errors:
        raise ValueError("invalid analysis spec: " + "; ".join(errors))
    _verify_source_artifacts(root, manifest)
    packages = manifest["packages"]
    raw_packages: dict[str, dict] = {}
    for section in spec.sections:
        package_meta = packages[section]
        package_path = _safe_path(root, package_meta["path"])
        if not package_path.is_file():
            raise ValueError(f"fact package is missing: {package_meta['path']}")
        package = _read_json(package_path)
        if not isinstance(package, dict) or not isinstance(package.get("records"), list):
            raise ValueError(f"fact package records must be an array: {package_meta['path']}")
        if package.get("schema_version") != manifest.get("schema_version"):
            raise ValueError(f"fact package schema version mismatch: {package_meta['path']}")
        if len(package["records"]) != package_meta.get("record_count"):
            raise ValueError(f"fact package record_count mismatch: {package_meta['path']}")
        expected_hash = package_meta.get("sha256")
        if manifest.get("schema_version", 1) >= 2 and not expected_hash:
            raise ValueError(f"fact package SHA-256 is missing from manifest: {package_meta['path']}")
        if expected_hash is not None:
            if not isinstance(expected_hash, str) or _sha256(package_path) != expected_hash:
                raise ValueError(f"fact package SHA-256 mismatch: {package_meta['path']}")
        raw_packages[section] = {"package": package, "meta": package_meta}

    ranking_records = raw_packages.get("material_ranking", {}).get("package", {}).get("records", [])
    ranking_ids = {
        str(record.get("material_id"))
        for record in ranking_records
        if isinstance(record, dict) and record.get("material_id") is not None
        and spec.filters["rank_range"][0] <= record.get("rank", 0) <= spec.filters["rank_range"][1]
    }
    result = {"manifest": manifest, "sections": {}}
    for section, item in raw_packages.items():
        selected_records = _selected_records(item["package"]["records"], spec, section, ranking_ids)
        result["sections"][section] = {
            "path": item["meta"]["path"],
            "schema_version": item["package"].get("schema_version"),
            "record_count": len(selected_records),
            "source_record_count": len(item["package"]["records"]),
            "source_paths": item["meta"].get("source_paths", []),
            "record_indices": [index for index, _ in selected_records],
            "records": [record for _, record in selected_records],
        }
    return result


def build_fact_index(selected_facts: dict) -> dict[str, object]:
    """Index JSON-pointer-like refs to the exact selected record objects."""
    sections = selected_facts.get("sections") if isinstance(selected_facts, dict) else None
    if not isinstance(sections, dict):
        raise ValueError("selected_facts sections must be an object")
    index: dict[str, object] = {}
    for section in sections.values():
        if not isinstance(section, dict):
            raise ValueError("selected fact section must be an object")
        path = section.get("path")
        records = section.get("records")
        if not isinstance(path, str) or not isinstance(records, list):
            raise ValueError("selected fact section requires path and records")
        record_indices = section.get("record_indices", list(range(len(records))))
        if not isinstance(record_indices, list) or len(record_indices) != len(records):
            raise ValueError("selected fact section record_indices must match records")
        for original_index, record in zip(record_indices, records):
            if not isinstance(original_index, int) or original_index < 0:
                raise ValueError("selected fact record index must be a nonnegative integer")
            index[f"{path}#/records/{original_index}"] = record
    return index
