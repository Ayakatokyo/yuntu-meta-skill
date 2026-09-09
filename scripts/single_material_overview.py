"""Project only detail-RPA materials into a safe, offline single-material workbench."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import shutil
from typing import Any, Mapping

try:
    from material_field_registry import MaterialFieldRegistry
except ImportError:
    from .material_field_registry import MaterialFieldRegistry


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_TREND_NAMES = ("点赞指数", "流失指数", "点击指数", "互动指数", "评论指数")
_CORE_METRIC_PREFIX = "metrics."
_TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "config/yuntu-content-formula-taxonomy-v1.json"
_DETAIL_RATE_METRIC_ALIASES = {
    "likeRate": "like_rate",
    "like_rate": "like_rate",
    "commentRate": "comment_rate",
    "comment_rate": "comment_rate",
    "shareRate": "share_rate",
    "share_rate": "share_rate",
    "productWishButtonBuyCartRate": "product_wish_button_buy_cart_rate",
    "product_wish_button_buy_cart_rate": "product_wish_button_buy_cart_rate",
}


class SingleMaterialOverviewError(ValueError):
    """Raised when detail-scoped facts or assets cannot be trusted."""


def _read_json(path: Path, label: str, expected_type: type) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SingleMaterialOverviewError(f"{label} is missing or unreadable") from exc
    if not isinstance(value, expected_type):
        raise SingleMaterialOverviewError(f"{label} has invalid shape")
    return value


def _text(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if re.search(r"(?:https?|file)://|(?:^|[\\/])(?:Users|home|var|tmp)(?:[\\/]|$)", value, re.I):
        return None
    return value


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return _text(value)


def _safe_value(value: Any) -> Any:
    if isinstance(value, list):
        return [item for item in (_safe_scalar(item) for item in value) if item is not None]
    if isinstance(value, Mapping):
        return None
    return _safe_scalar(value)


def _safe_path(root: Path, raw_path: Any, label: str) -> tuple[Path, str]:
    path_text = _text(raw_path)
    if path_text is None or "\\" in path_text or "\x00" in path_text:
        raise SingleMaterialOverviewError(f"{label} must be a safe relative path")
    path = Path(path_text)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise SingleMaterialOverviewError(f"{label} must be a safe relative path")
    resolved = (root / path).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise SingleMaterialOverviewError(f"{label} escapes run") from exc
    return resolved, relative.as_posix()


def _verify_file(root: Path, metadata: Mapping[str, Any], label: str) -> tuple[Path, str, bytes]:
    path, relative = _safe_path(root, metadata.get("path"), f"{label} path")
    if not path.is_file():
        raise SingleMaterialOverviewError(f"{label} is missing")
    expected = metadata.get("sha256")
    if not isinstance(expected, str) or not _SHA256.fullmatch(expected):
        raise SingleMaterialOverviewError(f"{label} sha256 is invalid")
    content = path.read_bytes()
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected.lower():
        raise SingleMaterialOverviewError(f"{label} sha256 does not match source")
    declared_size = metadata.get("sizeBytes", metadata.get("size_bytes"))
    if declared_size is not None and (type(declared_size) is not int or declared_size != len(content)):
        raise SingleMaterialOverviewError(f"{label} size does not match source")
    return path, relative, content


def _package(root: Path, manifest: Mapping[str, Any], name: str, expected_count: int | None = None) -> tuple[dict, list[dict]]:
    packages = manifest.get("packages")
    package = packages.get(name) if isinstance(packages, Mapping) else None
    if not isinstance(package, dict):
        raise SingleMaterialOverviewError(f"facts manifest {name} package is missing")
    _verify_file(root, package, f"{name} package")
    payload = _read_json(root / package["path"], f"{name} package", dict)
    records = payload.get("records")
    count = package.get("record_count")
    if not isinstance(records, list) or type(count) is not int or len(records) != count:
        raise SingleMaterialOverviewError(f"{name} package record_count does not match facts")
    if expected_count is not None and count != expected_count:
        raise SingleMaterialOverviewError(f"{name} package count does not match coverage")
    ids = [record.get("material_id") for record in records if isinstance(record, dict)]
    if len(ids) != len(records) or any(not isinstance(item, str) or not item.strip() for item in ids):
        raise SingleMaterialOverviewError(f"{name} package material IDs are invalid")
    if len(set(ids)) != len(ids):
        raise SingleMaterialOverviewError(f"{name} package contains duplicate material IDs")
    declared_ids = package.get("material_ids")
    if not isinstance(declared_ids, list) or set(declared_ids) != set(ids) or len(declared_ids) != len(ids):
        raise SingleMaterialOverviewError(f"{name} package material_ids do not match facts")
    return package, records


def _record_map(records: list[dict], label: str) -> dict[str, dict]:
    result = {}
    for index, record in enumerate(records):
        material_id = _text(record.get("material_id"))
        if material_id is None:
            raise SingleMaterialOverviewError(f"{label} record {index} material_id is invalid")
        if material_id in result:
            raise SingleMaterialOverviewError(f"{label} contains duplicate material IDs")
        result[material_id] = record
    return result


def _verify_source_artifacts(root: Path, manifest: Mapping[str, Any], relative_paths: set[str]) -> None:
    entries = manifest.get("source_artifacts")
    if not isinstance(entries, list):
        raise SingleMaterialOverviewError("facts source artifacts are missing")
    by_path = {item.get("path"): item for item in entries if isinstance(item, dict)}
    for relative in relative_paths:
        metadata = by_path.get(relative)
        if not isinstance(metadata, dict):
            raise SingleMaterialOverviewError(f"facts source artifact declaration is missing: {relative}")
        _verify_file(root, metadata, f"facts source {relative}")


def _verify_run(root: Path) -> tuple[dict, dict, dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict], dict[str, dict]]:
    summary = _read_json(root / "run-summary.json", "run summary", dict)
    run_id = _text(summary.get("runId"))
    if run_id is None:
        raise SingleMaterialOverviewError("run summary runId is required")
    if summary.get("collectionStatus", summary.get("status")) not in {"success", "succeeded", "ready_for_analysis", "analysis_completed"}:
        raise SingleMaterialOverviewError("run is not a completed successful collection")
    facts_manifest = _read_json(root / "facts/manifest.json", "facts manifest", dict)
    if facts_manifest.get("run_id") != run_id:
        raise SingleMaterialOverviewError("facts manifest run_id does not match run summary")
    coverage = facts_manifest.get("coverage")
    if not isinstance(coverage, dict) or coverage.get("detail_records") is None:
        raise SingleMaterialOverviewError("facts detail coverage is missing")
    ranking_package, ranking = _package(root, facts_manifest, "material_ranking", coverage.get("ranking_records"))
    _, audience = _package(root, facts_manifest, "audience", coverage.get("ranking_records"))
    _, interaction = _package(root, facts_manifest, "interaction_series", coverage.get("detail_records"))
    _, script = _package(root, facts_manifest, "script", coverage.get("detail_records"))
    _, highlights = _package(root, facts_manifest, "highlight_frames", coverage.get("highlight_materials"))
    list_artifact = summary.get("artifacts", {}).get("listRecords") if isinstance(summary.get("artifacts"), dict) else None
    if not isinstance(list_artifact, dict):
        raise SingleMaterialOverviewError("run summary listRecords artifact is missing")
    _, list_relative, _ = _verify_file(root, list_artifact, "list records")
    list_rows = _read_json(root / list_relative, "list records", list)
    if len(list_rows) != ranking_package.get("record_count"):
        raise SingleMaterialOverviewError("list records count does not match ranking facts")
    task_runs = summary.get("taskRuns")
    if not isinstance(task_runs, dict):
        raise SingleMaterialOverviewError("detail task runs are missing")
    detail_ids = set()
    artifacts = summary.get("artifacts")
    if not isinstance(artifacts, dict):
        raise SingleMaterialOverviewError("run summary artifacts are missing")
    for key, task in task_runs.items():
        if not isinstance(task, dict) or task.get("operation") != "detail":
            continue
        material_id = _text(task.get("material_id"))
        if material_id is None or task.get("status") not in {"persisted", "success", "completed"}:
            continue
        if not key.endswith(material_id):
            raise SingleMaterialOverviewError("detail task run key does not match material ID")
        artifact = artifacts.get(f"detailRecord:{material_id}")
        if not isinstance(artifact, dict):
            raise SingleMaterialOverviewError(f"detail record artifact is missing: {material_id}")
        _verify_file(root, artifact, f"detail record {material_id}")
        detail_ids.add(material_id)
    expected_detail_ids = set(_record_map(script, "script"))
    ranking_ids = set(_record_map(ranking, "material ranking"))
    if not expected_detail_ids.issubset(ranking_ids):
        raise SingleMaterialOverviewError("detail material IDs are missing from ranking facts")
    if detail_ids != expected_detail_ids:
        raise SingleMaterialOverviewError("persisted detail IDs do not match script facts")
    if set(_record_map(interaction, "interaction series")) != detail_ids or set(_record_map(highlights, "highlight frames")) != detail_ids:
        raise SingleMaterialOverviewError("detail package material IDs do not match")
    _verify_source_artifacts(root, facts_manifest, {
        list_relative,
        "highlights-manifest.json",
        *(f"normalized/detail-records/{material_id}.json" for material_id in detail_ids),
    })
    highlight_manifest = _read_json(root / "highlights-manifest.json", "highlights manifest", dict)
    manifest_materials = highlight_manifest.get("materials")
    if not isinstance(manifest_materials, list):
        raise SingleMaterialOverviewError("highlights manifest materials are invalid")
    manifest_map = _record_map(manifest_materials, "highlights manifest")
    if set(manifest_map) != detail_ids:
        raise SingleMaterialOverviewError("highlights manifest material IDs do not match detail facts")
    return (
        summary,
        facts_manifest,
        _record_map(ranking, "material ranking"),
        _record_map(audience, "audience"),
        _record_map(interaction, "interaction series"),
        _record_map(script, "script"),
        _record_map(highlights, "highlight frames"),
        manifest_map,
    )


def _availability(record: Mapping[str, Any], key: str) -> tuple[bool, str]:
    availability = record.get("data_availability")
    value = availability.get(key) if isinstance(availability, Mapping) else None
    if isinstance(value, Mapping) and value.get("available") is True:
        return True, ""
    reason = _text(value.get("missing_reason")) if isinstance(value, Mapping) else None
    return False, reason or "source_empty"


def _taxonomy() -> dict[str, dict[str, str]]:
    payload = _read_json(_TAXONOMY_PATH, "formula taxonomy", dict)
    if payload.get("schemaVersion") != 1 or not isinstance(payload.get("primary"), dict) or not isinstance(payload.get("secondary"), dict):
        raise SingleMaterialOverviewError("formula taxonomy is invalid")
    return {level: {str(key): value for key, value in payload[level].items() if isinstance(value, str)} for level in ("primary", "secondary")}


def _project_core(ranking: Mapping[str, Any], registry: MaterialFieldRegistry) -> dict:
    fields = []
    for definition in registry.definitions():
        if not definition.id.startswith(_CORE_METRIC_PREFIX):
            continue
        fields.append({"id": definition.id, "label": definition.label, "kind": definition.kind, "value": _safe_value(registry.value(ranking, definition.id))})
    return {"status": "available", "fields": fields, "defaultFieldIds": [
        field_id for field_id in (
            "metrics.show_cnt", "metrics.play_3s_rate", "metrics.play_over_rate",
            "metrics.ctr", "metrics.cvr", "metrics.pvr", "metrics.interact_rate",
        ) if any(field["id"] == field_id for field in fields)
    ]}


def _merge_detail_rate_metrics(root: Path, material_id: str, ranking: Mapping[str, Any]) -> dict:
    """Fill newly exposed rates from the verified detail artifact when the list snapshot predates them."""
    detail = _read_json(
        root / "normalized/detail-records" / f"{material_id}.json",
        f"detail record {material_id}",
        dict,
    )
    source = detail.get("core_metrics") or detail.get("metrics")
    if not isinstance(source, Mapping):
        return dict(ranking)
    merged = dict(ranking)
    metrics = dict(ranking.get("metrics")) if isinstance(ranking.get("metrics"), Mapping) else {}
    for source_name, target_name in _DETAIL_RATE_METRIC_ALIASES.items():
        value = source.get(source_name)
        if (
            target_name not in metrics
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        ):
            metrics[target_name] = value
    merged["metrics"] = metrics
    return merged


def _project_portrait(script: Mapping[str, Any]) -> dict:
    available, reason = _availability(script, "audience_portrait")
    portrait = script.get("audience_portrait") if available else None
    if not isinstance(portrait, Mapping):
        return {"status": "unavailable", "reason": reason, "eightCrowds": [], "ageFeatures": [], "genderFeatures": []}
    return {"status": "available", "reason": "", "eightCrowds": _safe_value(portrait.get("eightCrowds")) or [], "ageFeatures": _safe_value(portrait.get("ageFeatures")) or [], "genderFeatures": _safe_value(portrait.get("genderFeatures")) or []}


def _project_trends(interaction: Mapping[str, Any]) -> dict:
    available, reason = _availability(interaction, "trends")
    source = interaction.get("trend_series") if available else []
    by_name = {item.get("trend_name"): item for item in source if isinstance(item, Mapping) and _text(item.get("trend_name"))}
    metrics = []
    for name in _TREND_NAMES:
        item = by_name.get(name)
        series = item.get("series") if isinstance(item, Mapping) else None
        normalized = []
        if isinstance(series, list):
            for point in series:
                if not isinstance(point, Mapping) or type(point.get("second")) is not int or isinstance(point.get("value"), bool) or not isinstance(point.get("value"), (int, float)) or not math.isfinite(point["value"]):
                    continue
                normalized.append({"second": point["second"], "value": point["value"]})
        metrics.append({"id": name, "label": name, "status": "available" if normalized else "unavailable", "reason": "" if normalized else (reason or "source_empty"), "series": normalized})
    return {"status": "available" if any(item["status"] == "available" for item in metrics) else "unavailable", "metrics": metrics}


def _project_formula(script: Mapping[str, Any]) -> dict:
    available, reason = _availability(script, "content_formula")
    formula = script.get("content_formula") if available else None
    if not isinstance(formula, Mapping) or not isinstance(formula.get("labels"), list) or formula.get("labels") == []:
        return {"status": "unavailable", "reason": reason or "source_empty", "labels": [], "sources": {}, "links": []}
    taxonomy = _taxonomy()
    labels = []
    ids: set[str] = set()
    unknown_id = False
    for item in formula["labels"]:
        if not isinstance(item, Mapping):
            unknown_id = True
            continue
        primary_id = str(item.get("level_1_label")) if type(item.get("level_1_label")) is int else None
        if primary_id is None or primary_id not in taxonomy["primary"]:
            unknown_id = True
            continue
        ids.add(primary_id)
        secondary = []
        for raw_id in item.get("level_2_labels", []):
            if type(raw_id) is not int:
                unknown_id = True
                continue
            secondary_id = str(raw_id)
            if secondary_id in taxonomy["secondary"]:
                ids.add(secondary_id)
                secondary.append({"id": secondary_id, "label": taxonomy["secondary"][secondary_id]})
            else:
                unknown_id = True
        labels.append({"id": primary_id, "label": taxonomy["primary"][primary_id], "secondary": secondary})
    if unknown_id or not labels:
        return {"status": "unavailable", "reason": "formula_taxonomy_id_unknown", "labels": [], "sources": {}, "links": []}
    sources = {}
    links = []
    raw_sources = formula.get("sources")
    if isinstance(raw_sources, Mapping):
        for source_name in ("title", "visual", "script"):
            source = raw_sources.get(source_name)
            if not isinstance(source, Mapping):
                continue
            source_text = _safe_scalar(source.get("text"))
            details = source.get("detail")
            terms = []
            if isinstance(details, Mapping):
                for ref_id, raw_terms in details.items():
                    ref_id = str(ref_id)
                    if ref_id not in ids or not isinstance(raw_terms, list):
                        continue
                    safe_terms = [item for item in (_safe_scalar(term) for term in raw_terms) if item is not None]
                    if safe_terms:
                        terms.append({"id": ref_id, "texts": safe_terms})
                        links.append({"id": ref_id, "source": source_name, "texts": safe_terms})
            sources[source_name] = {"text": source_text, "terms": terms}
    return {"status": "available", "reason": "", "labels": labels, "sources": sources, "links": links}


def _reason(value: Any) -> dict | None:
    if not isinstance(value, Mapping) or value.get("type") not in {"cover", "local_peak", "top_values"}:
        return None
    if value.get("type") == "cover":
        return {"type": "cover"}
    if not isinstance(value.get("trend_name"), str) or isinstance(value.get("value"), bool) or not isinstance(value.get("value"), (int, float)) or not math.isfinite(value["value"]) or type(value.get("rank")) is not int or value["rank"] < 1:
        return None
    return {"type": value["type"], "trendName": value["trend_name"].strip(), "value": value["value"], "rank": value["rank"], "withinHighPoint": value.get("within_high_point") if isinstance(value.get("within_high_point"), bool) else None}


def _project_highlights(root: Path, facts: Mapping[str, Any], manifest: Mapping[str, Any], material_id: str) -> tuple[dict, list[tuple[dict, Path]]]:
    fact_frames = facts.get("frames")
    manifest_frames = manifest.get("frames")
    if not isinstance(fact_frames, list) or not isinstance(manifest_frames, list):
        return {"status": "unavailable", "reason": "frames_missing", "frames": []}, []
    if len(fact_frames) != len(manifest_frames):
        raise SingleMaterialOverviewError(f"highlight frame count does not match: {material_id}")
    frames = []
    assets = []
    for index, (fact, declared) in enumerate(zip(fact_frames, manifest_frames), start=1):
        if not isinstance(fact, Mapping) or not isinstance(declared, Mapping) or any(fact.get(key) != declared.get(key) for key in ("second", "is_cover", "frame_type", "reasons", "available", "relative_path")):
            raise SingleMaterialOverviewError(f"highlight frame binding does not match: {material_id}")
        if fact.get("available") is not True:
            continue
        path, relative = _safe_path(root, declared.get("relative_path"), "frame path")
        if path.suffix.lower() not in _IMAGE_EXTENSIONS or not path.is_file():
            continue
        content = path.read_bytes()
        reasons = [_reason(item) for item in fact.get("reasons", [])] if isinstance(fact.get("reasons"), list) else []
        if not reasons or any(item is None for item in reasons):
            continue
        digest = hashlib.sha256(content).hexdigest()
        frame = {"id": f"highlight:{material_id}:{index}:{fact.get('second')}", "second": fact.get("second"), "role": "视频开场画面" if fact.get("is_cover") is True or fact.get("frame_type") == "cover" else "指标高光帧", "reasons": reasons, "assetPath": f"assets/single-material/{digest}{path.suffix.lower()}", "assetSha256": digest, "assetSizeBytes": len(content)}
        frames.append(frame)
        assets.append((frame, path))
    return {"status": "available" if frames else "unavailable", "reason": "" if frames else "verified_frame_missing", "frames": frames}, assets


def build_single_material_overview(run_dir: Path) -> dict:
    root = Path(run_dir).resolve()
    if not root.is_dir():
        raise SingleMaterialOverviewError("run directory is missing")
    summary, facts_manifest, ranking, audience, interaction, script, highlights, highlight_manifest = _verify_run(root)
    registry = MaterialFieldRegistry.from_path(Path(__file__).resolve().parents[1] / "config/yuntu-material-field-registry-v1.json")
    detail_ids = set(script)
    materials = []
    for material_id in sorted(detail_ids, key=lambda item: (ranking[item].get("rank", 10**9), item)):
        ranking_record = _merge_detail_rate_metrics(root, material_id, ranking[material_id])
        script_record = script[material_id]
        highlight_model, _ = _project_highlights(root, highlights[material_id], highlight_manifest[material_id], material_id)
        materials.append({
            "materialId": material_id,
            "rank": ranking_record.get("rank"),
            "title": _safe_scalar(ranking_record.get("title")),
            "publishTime": _safe_scalar(ranking_record.get("publish_time")),
            "core": _project_core(ranking_record, registry),
            "portrait": _project_portrait(script_record),
            "trends": _project_trends(interaction[material_id]),
            "formula": _project_formula(script_record),
            "creative": {"status": "deferred", "message": "本阶段暂未设计"},
            "video": {"available": False, "reason": "local_video_artifact_missing"},
            "highlights": highlight_model,
        })
    return {
        "schemaVersion": 1,
        "kind": "yuntu_single_material_overview",
        "status": "available" if materials else "unavailable",
        "materialCount": len(materials),
        "source": {"rankingRecordCount": facts_manifest["coverage"]["ranking_records"], "detailRecordCount": len(materials), "verifiedFrameCount": sum(len(item["highlights"]["frames"]) for item in materials)},
        "materials": materials,
    }


def copy_verified_single_material_assets(run_dir: Path, output_dir: Path, model: Mapping[str, Any]) -> int:
    root = Path(run_dir).resolve()
    output = Path(output_dir).resolve()
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise SingleMaterialOverviewError("output directory must remain inside the run") from exc
    current = build_single_material_overview(root)
    expected = [(frame["id"], frame["assetPath"], frame["assetSha256"], frame["assetSizeBytes"]) for material in model.get("materials", []) for frame in material.get("highlights", {}).get("frames", [])]
    actual = [(frame["id"], frame["assetPath"], frame["assetSha256"], frame["assetSizeBytes"]) for material in current.get("materials", []) for frame in material.get("highlights", {}).get("frames", [])]
    if expected != actual:
        raise SingleMaterialOverviewError("single-material overview changed before asset copy")
    source_by_id = {}
    # Re-resolve through the verified model and run facts, without trusting model paths as source paths.
    _, _, _, _, _, _, highlight_facts, highlight_manifests = _verify_run(root)
    for material_id, fact in highlight_facts.items():
        _, assets = _project_highlights(root, fact, highlight_manifests[material_id], material_id)
        source_by_id.update({frame["id"]: path for frame, path in assets})
    copied = 0
    for material in model.get("materials", []):
        for frame in material.get("highlights", {}).get("frames", []):
            source = source_by_id.get(frame["id"])
            if source is None:
                raise SingleMaterialOverviewError(f"verified frame source is missing: {frame['id']}")
            destination = output / frame["assetPath"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            content = destination.read_bytes()
            if len(content) != frame["assetSizeBytes"] or hashlib.sha256(content).hexdigest() != frame["assetSha256"]:
                raise SingleMaterialOverviewError(f"copied frame failed verification: {frame['id']}")
            copied += 1
    return copied
