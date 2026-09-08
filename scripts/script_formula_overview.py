"""Build a strict, taxonomy-bound script formula overview."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from audience_overview import AudienceOverviewError, _load_manifest_package, _read_json, _safe_path, _verify_file
except ImportError:
    from .audience_overview import AudienceOverviewError, _load_manifest_package, _read_json, _safe_path, _verify_file


class ScriptFormulaOverviewError(ValueError):
    """Raised when script formula facts cannot be verified safely."""


_TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "config/yuntu-content-formula-taxonomy-v1.json"


def _gap(gaps: dict[str, int], code: str) -> None:
    gaps[code] = gaps.get(code, 0) + 1


def _verify_detail_sources(root: Path, summary: dict, records: list[dict]) -> None:
    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, dict):
        raise ScriptFormulaOverviewError("detail source declarations are missing")
    for record in records:
        material_id = str(record.get("material_id", ""))
        source_paths = record.get("source_paths")
        normalized = source_paths.get("normalized") if isinstance(source_paths, dict) else None
        expected_path = f"normalized/detail-records/{material_id}.json"
        if normalized != expected_path:
            raise ScriptFormulaOverviewError("detail normalized source path is invalid")
        artifact = artifacts.get(f"detailRecord:{material_id}")
        if not isinstance(artifact, dict) or artifact.get("path") != expected_path:
            raise ScriptFormulaOverviewError("detail source declaration is missing")
        _verify_file(_safe_path(root, expected_path, "detail source path"), artifact, "detail source")


def _load_taxonomy() -> dict[str, object]:
    try:
        taxonomy = json.loads(_TAXONOMY_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScriptFormulaOverviewError("formula taxonomy is missing or unreadable") from exc
    version = taxonomy.get("version")
    if taxonomy.get("schemaVersion") != 1 or not isinstance(version, str) or not version.strip():
        raise ScriptFormulaOverviewError("formula taxonomy version is invalid")
    primary, secondary = taxonomy.get("primary"), taxonomy.get("secondary")
    if not isinstance(primary, dict) or not isinstance(secondary, dict):
        raise ScriptFormulaOverviewError("formula taxonomy is invalid")
    for mapping in (primary, secondary):
        if any(not isinstance(key, str) or not isinstance(value, str) or not value.strip() for key, value in mapping.items()):
            raise ScriptFormulaOverviewError("formula taxonomy mapping is invalid")
    return {"version": version.strip(), "primary": primary, "secondary": secondary}


def _resolve_formula_ref(value: object, taxonomy: dict[str, object], level: str) -> tuple[str | None, str | None, list[str]]:
    mapping = taxonomy.get(level)
    if not isinstance(mapping, dict):
        return None, None, ["formula_hierarchy_unavailable"]
    if type(value) is int:
        ref_id = str(value)
        label = mapping.get(ref_id)
        return ref_id, label, [] if isinstance(label, str) else ["formula_taxonomy_unmapped"]
    if isinstance(value, dict):
        ref_id = value.get("id")
        source_label = value.get("label")
        if type(ref_id) is not int or not isinstance(source_label, str) or not source_label.strip():
            return None, None, ["formula_hierarchy_unavailable"]
        ref_id_text = str(ref_id)
        label = source_label.strip()
        gaps = []
        fallback = mapping.get(ref_id_text)
        if isinstance(fallback, str) and fallback != label:
            gaps.append("formula_taxonomy_label_conflict")
        return ref_id_text, label, gaps
    return None, None, ["formula_hierarchy_unavailable"]


def build_script_formula_overview(run_dir: Path) -> dict:
    root = Path(run_dir).resolve()
    try:
        _, summary, package = _load_manifest_package(root, "script")
        records = _read_json(_safe_path(root, package["path"], "script package path"), "script facts", dict).get("records")
    except AudienceOverviewError as exc:
        raise ScriptFormulaOverviewError(str(exc)) from exc
    expected_count = package.get("record_count")
    if type(expected_count) is not int or not isinstance(records, list) or len(records) != expected_count:
        raise ScriptFormulaOverviewError("script record_count does not match facts")
    package_sources = package.get("source_paths")
    if not isinstance(package_sources, list) or "normalized/detail-records/" not in package_sources:
        raise ScriptFormulaOverviewError("script normalized source declaration is missing")
    declared_ids = package.get("material_ids")
    actual_ids = [record.get("material_id") for record in records if isinstance(record, dict)]
    if not isinstance(declared_ids, list) or set(actual_ids) != set(declared_ids) or len(set(actual_ids)) != len(actual_ids):
        raise ScriptFormulaOverviewError("script material_ids do not match facts")
    try:
        _verify_detail_sources(root, summary, records)
    except AudienceOverviewError as exc:
        raise ScriptFormulaOverviewError(str(exc)) from exc
    taxonomy = _load_taxonomy()
    primary_ids: dict[str, set[str]] = {}
    secondary_ids: dict[str, dict[str, set[str]]] = {}
    gaps: dict[str, int] = {}
    entries: list[tuple[str, str, str, list[tuple[str, str]]]] = []
    explicit_names: dict[tuple[str, str], set[str]] = {}
    for record in records:
        material_id = str(record["material_id"])
        availability = record.get("data_availability", {}).get("content_formula") if isinstance(record.get("data_availability"), dict) else None
        formula = record.get("content_formula")
        if not isinstance(availability, dict) or availability.get("available") is not True or not isinstance(formula, dict):
            _gap(gaps, "formula_source_empty")
            continue
        labels = formula.get("labels")
        if labels == []:
            _gap(gaps, "formula_source_empty")
            continue
        if not isinstance(labels, list):
            _gap(gaps, "formula_hierarchy_unavailable")
            continue
        for item in labels:
            if not isinstance(item, dict) or not isinstance(item.get("level_2_labels"), list):
                _gap(gaps, "formula_hierarchy_unavailable")
                continue
            primary_id, primary_label, primary_gaps = _resolve_formula_ref(item.get("level_1_label"), taxonomy, "primary")
            for code in primary_gaps:
                _gap(gaps, code)
            if primary_id is None or primary_label is None:
                continue
            if isinstance(item.get("level_1_label"), dict):
                explicit_names.setdefault(("primary", primary_id), set()).add(primary_label)
            secondary_entries: list[tuple[str, str]] = []
            for secondary_id in item["level_2_labels"]:
                secondary_ref_id, secondary_label, secondary_gaps = _resolve_formula_ref(secondary_id, taxonomy, "secondary")
                for code in secondary_gaps:
                    _gap(gaps, code)
                if secondary_ref_id is None or secondary_label is None:
                    continue
                secondary_entries.append((secondary_ref_id, secondary_label))
                if isinstance(secondary_id, dict):
                    explicit_names.setdefault(("secondary", secondary_ref_id), set()).add(secondary_label)
            entries.append((material_id, primary_id, primary_label, secondary_entries))
    conflicting_ids = {key: names for key, names in explicit_names.items() if len(names) > 1}
    for _level, _ref_id in conflicting_ids:
        _gap(gaps, "formula_source_label_conflict")
    for material_id, primary_id, primary_label, secondary_entries in entries:
        if ("primary", primary_id) in conflicting_ids:
            continue
        primary_ids.setdefault(primary_label, set()).add(material_id)
        for secondary_id, secondary_label in secondary_entries:
            if ("secondary", secondary_id) in conflicting_ids:
                continue
            secondary_ids.setdefault(primary_label, {}).setdefault(secondary_label, set()).add(material_id)
    formula_materials = set().union(*primary_ids.values()) if primary_ids else set()
    primary_total = len(formula_materials)
    primary_buckets = []
    for label, materials in sorted(primary_ids.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        primary_buckets.append({"label": label, "value": len(materials), "share": len(materials) / primary_total if primary_total else 0})
    secondary_buckets: dict[str, list[dict]] = {}
    for primary, buckets in secondary_ids.items():
        total = len(primary_ids[primary])
        secondary_buckets[primary] = [
            {"label": label, "value": len(materials), "share": len(materials) / total if total else 0}
            for label, materials in sorted(buckets.items(), key=lambda pair: (-len(pair[1]), pair[0]))
        ]
    return {
        "schemaVersion": 1,
        "status": "available",
        "source": {"path": "facts/script.json", "recordCount": len(records), "taxonomyVersion": taxonomy["version"]},
        "coverage": {"scriptMaterialCount": len(records), "formulaMaterialCount": len(formula_materials)},
        "primaryBuckets": primary_buckets,
        "secondaryBucketsByPrimary": secondary_buckets,
        "gaps": [{"code": code, "count": count} for code, count in sorted(gaps.items())],
    }
