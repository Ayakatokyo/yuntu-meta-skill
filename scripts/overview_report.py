"""Build a verified, redacted and self-contained Yuntu leaderboard overview."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Mapping

try:
    from material_field_registry import MaterialFieldRegistry, MaterialFieldRegistryError
except ImportError:
    from .material_field_registry import MaterialFieldRegistry, MaterialFieldRegistryError

try:
    from audience_overview import AudienceOverviewError, build_audience_overview
    from script_formula_overview import ScriptFormulaOverviewError, build_script_formula_overview
    from highlight_overview import (
        HighlightOverviewError,
        build_highlight_overview,
        copy_verified_highlight_assets,
    )
except ImportError:
    from .audience_overview import AudienceOverviewError, build_audience_overview
    from .script_formula_overview import ScriptFormulaOverviewError, build_script_formula_overview
    from .highlight_overview import (
        HighlightOverviewError,
        build_highlight_overview,
        copy_verified_highlight_assets,
    )


SCHEMA_VERSION = 1
OVERVIEW_KIND = "yuntu_material_leaderboard_overview"
PAGE_SIZE = 10
FIELD_GROUPS = {
    "title": "素材基础信息",
    "publish_time": "素材基础信息",
    "video_duration": "素材基础信息",
    "rank": "素材基础信息",
    "material_uri": "素材基础信息",
    "people_tags": "素材基础信息",
    "material_tags": "素材基础信息",
    "metrics.show_cnt": "内容曝光与播放",
    "metrics.play_3s_rate": "内容曝光与播放",
    "metrics.play_5s_rate": "内容曝光与播放",
    "metrics.play_over_rate": "内容曝光与播放",
    "metrics.ctr": "点击与转化",
    "metrics.component_click_rate": "点击与转化",
    "metrics.cvr": "点击与转化",
    "metrics.pvr": "点击与转化",
    "metrics.interact_rate": "互动指标",
}
FIELD_GROUP_ORDER = tuple(dict.fromkeys(FIELD_GROUPS.values()))
DEFAULT_FIELD_IDS = (
    "title",
    "publish_time",
    "metrics.show_cnt",
    "metrics.play_3s_rate",
    "metrics.play_over_rate",
    "metrics.ctr",
    "metrics.cvr",
    "metrics.pvr",
    "metrics.interact_rate",
)
_SENSITIVE_TOKENS = {"account_id", "shop_id", "advertiser_id", "credential", "token", "password"}
_SENSITIVE_TEXT = re.compile(
    r"(?:https?|file)://|(?:^|[\\/])(?:Users|home|var|tmp)(?:[\\/]|$)", re.IGNORECASE
)
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class OverviewReportError(ValueError):
    """Raised when a run cannot produce a trustworthy overview."""


def _read_json(path: Path, label: str, expected_type: type) -> Any:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OverviewReportError(f"{label} is missing or unreadable") from exc
    if not isinstance(payload, expected_type):
        expected = "object" if expected_type is dict else "list"
        raise OverviewReportError(f"{label} must be a {expected}")
    return payload


def _nonblank(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OverviewReportError(f"{label} is required")
    return value.strip()


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or _SENSITIVE_TEXT.search(value):
        return None
    if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
        return None
    return value


def _safe_value(value: Any) -> Any:
    if isinstance(value, list):
        result = []
        for item in value:
            item = _safe_scalar(item)
            if item is not None:
                result.append(item)
        return result
    if isinstance(value, Mapping):
        return None
    return _safe_scalar(value)


def _resolve_relative_path(run_root: Path, raw_path: Any) -> tuple[Path, str]:
    path_text = _nonblank(raw_path, "artifacts.listRecords.path")
    path = Path(path_text)
    if path.is_absolute() or "\\" in path_text or "\x00" in path_text:
        raise OverviewReportError("list records path must be a safe relative path")
    if not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise OverviewReportError("list records path must be a safe relative path")
    candidate = (run_root / path).resolve()
    try:
        relative = candidate.relative_to(run_root)
    except ValueError as exc:
        raise OverviewReportError("list records path must remain inside the run") from exc
    return candidate, relative.as_posix()


def _validate_run_and_source(run_root: Path) -> tuple[dict, Path, str, list]:
    if not run_root.is_dir():
        raise OverviewReportError("run directory is missing")
    summary = _read_json(run_root / "run-summary.json", "run summary", dict)
    run_id = _nonblank(summary.get("runId"), "run summary runId")
    status = summary.get("collectionStatus", summary.get("status"))
    if status is not None and status not in {"success", "succeeded", "analysis_completed"}:
        raise OverviewReportError("run is not a completed successful collection")
    list_stage = summary.get("stages", {}).get("list")
    if isinstance(list_stage, dict):
        if list_stage.get("normalized") is False or list_stage.get("contextVerified") is False:
            raise OverviewReportError("list source is not normalized and context-verified")
        if list_stage.get("requestStatus") in {"failed", "error", "cancelled"}:
            raise OverviewReportError("list collection did not succeed")

    artifacts = summary.get("artifacts")
    list_artifact = artifacts.get("listRecords") if isinstance(artifacts, dict) else None
    if not isinstance(list_artifact, dict):
        raise OverviewReportError("run summary listRecords artifact is missing")
    source_path, relative_path = _resolve_relative_path(run_root, list_artifact.get("path"))
    if not source_path.is_file():
        raise OverviewReportError("list records source file is missing")
    declared_hash = _nonblank(list_artifact.get("sha256"), "list records sha256")
    if not _SHA256.fullmatch(declared_hash):
        raise OverviewReportError("list records sha256 is invalid")
    source_bytes = source_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if source_hash != declared_hash.lower():
        raise OverviewReportError("list records sha256 does not match source")
    if list_artifact.get("sizeBytes") is not None:
        size = list_artifact.get("sizeBytes")
        if type(size) is not int or size != len(source_bytes):
            raise OverviewReportError("list records size does not match source")
    rows = _read_json(source_path, "list records source", list)
    if not rows:
        raise OverviewReportError("list records source must not be empty")
    if list_artifact.get("recordCount") is not None and list_artifact["recordCount"] != len(rows):
        raise OverviewReportError("list records record count does not match source")

    batch = _read_json(run_root / "batch-manifest.json", "batch manifest", dict)
    batch_run_id = batch.get("runId")
    if batch_run_id is not None and batch_run_id != run_id:
        raise OverviewReportError("batch manifest runId does not match run summary")
    candidate_top_n = batch.get("candidateTopN")
    if candidate_top_n is None and isinstance(batch.get("collectionContract"), dict):
        candidate_top_n = batch["collectionContract"].get("candidateTopN")
    if candidate_top_n is not None:
        if type(candidate_top_n) is not int or candidate_top_n != len(rows):
            raise OverviewReportError("batch manifest candidate record count does not match source")

    facts_manifest_path = run_root / "facts/manifest.json"
    if facts_manifest_path.is_file():
        facts = _read_json(facts_manifest_path, "facts manifest", dict)
        if facts.get("run_id") is not None and facts["run_id"] != run_id:
            raise OverviewReportError("facts manifest run_id does not match run summary")
        coverage = facts.get("coverage")
        ranking_records = coverage.get("ranking_records") if isinstance(coverage, dict) else None
        if ranking_records is not None and (type(ranking_records) is not int or ranking_records != len(rows)):
            raise OverviewReportError("facts manifest ranking record count does not match source")
    return summary, source_path, relative_path, rows


def _safe_context_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_safe_context_value(item) for item in value if _safe_context_value(item) is not None]
    return _safe_scalar(value)


def _is_sensitive_field(value: Any) -> bool:
    token = str(value or "").strip().casefold()
    return any(part in token for part in _SENSITIVE_TOKENS)


def _query_context(run_root: Path) -> dict:
    spec = _read_json(run_root / "resolved-query-spec.json", "resolved query spec", dict)
    context: dict[str, Any] = {}
    if _safe_scalar(spec.get("industry")) is not None:
        context["industry"] = _safe_scalar(spec["industry"])
    period = spec.get("period")
    if isinstance(period, dict):
        context["period"] = {
            key: _safe_scalar(period.get(key))
            for key in ("type", "start_date", "end_date")
            if _safe_scalar(period.get(key)) is not None
        }
    ranking = spec.get("ranking")
    if isinstance(ranking, dict):
        context["ranking"] = {
            key: _safe_scalar(ranking.get(key))
            for key in ("metric", "field", "direction")
            if _safe_scalar(ranking.get(key)) is not None
        }
    filters = spec.get("filters")
    safe_filters: dict[str, Any] = {}
    if isinstance(filters, dict):
        for key in ("ages", "genders", "crowd_groups"):
            value = _safe_context_value(filters.get(key))
            if value is not None:
                safe_filters[key] = value
        brand_scope = filters.get("brand_scope")
        if isinstance(brand_scope, dict):
            safe_filters["brand_scope"] = {
                key: _safe_context_value(brand_scope.get(key))
                for key in ("type", "brands")
                if _safe_context_value(brand_scope.get(key)) is not None
            }
    context["filters"] = safe_filters
    material_list = spec.get("material_list")
    safe_material_list: dict[str, Any] = {}
    if isinstance(material_list, dict):
        sort = material_list.get("sort")
        if isinstance(sort, dict):
            safe_material_list["sort"] = {
                key: _safe_scalar(sort.get(key))
                for key in ("field", "direction")
                if _safe_scalar(sort.get(key)) is not None
            }
        raw_filters = material_list.get("filters")
        if isinstance(raw_filters, list):
            safe_material_list["filters"] = [
                {
                    key: _safe_context_value(item.get(key))
                    for key in ("field", "operator", "value")
                    if _safe_context_value(item.get(key)) is not None
                }
                for item in raw_filters
                if isinstance(item, dict) and not _is_sensitive_field(item.get("field"))
            ]
    context["materialList"] = safe_material_list
    return context


def _value_type(kind: str) -> str:
    if kind == "rate":
        return "rate"
    if kind in {"number", "integer"}:
        return "number"
    if kind == "date":
        return "date"
    if kind == "string_list":
        return "list"
    return "text"


def build_overview_data(run_dir: Path, registry_path: Path) -> dict:
    run_root = Path(run_dir).resolve()
    summary, source_path, relative_path, source_rows = _validate_run_and_source(run_root)
    try:
        registry = MaterialFieldRegistry.from_path(Path(registry_path))
    except MaterialFieldRegistryError as exc:
        raise OverviewReportError(str(exc)) from exc

    definitions = registry.definitions()
    field_positions = {field.id: index for index, field in enumerate(definitions)}
    fields = []
    for definition in definitions:
        if definition.id == "material_id":
            continue
        group = FIELD_GROUPS.get(definition.id)
        if group is None:
            raise OverviewReportError(f"registry field is not allowed in overview: {definition.id}")
        fields.append({
            "id": definition.id,
            "label": definition.label,
            "group": group,
            "valueType": _value_type(definition.kind),
            "sortable": definition.sortable,
        })
    fields.sort(key=lambda field: (FIELD_GROUP_ORDER.index(field["group"]), field_positions[field["id"]]))
    field_map = {field["id"]: field for field in fields}

    rows = []
    material_ids = set()
    for index, record in enumerate(source_rows):
        if not isinstance(record, dict):
            raise OverviewReportError(f"list record {index} must be an object")
        material_id = _safe_scalar(record.get("material_id"))
        if material_id is None or isinstance(material_id, bool) or str(material_id).strip() == "":
            raise OverviewReportError(f"list record {index} has no material_id")
        material_id = str(material_id).strip()
        if material_id in material_ids:
            raise OverviewReportError(f"duplicate material_id: {material_id}")
        material_ids.add(material_id)
        values = {}
        for field in fields:
            value = _safe_value(registry.value(record, field["id"]))
            if field["valueType"] == "list" and value is None:
                value = []
            values[field["id"]] = value
        rows.append({"materialId": material_id, "values": values})

    default_ids = [field_id for field_id in DEFAULT_FIELD_IDS if field_id in field_map]
    for field in fields:
        field["defaultVisible"] = field["id"] in default_ids
    try:
        audience_overview = build_audience_overview(run_root)
    except AudienceOverviewError:
        audience_overview = {"schemaVersion": 1, "status": "unavailable", "gaps": [{"code": "audience_overview_unavailable"}]}
    try:
        script_formula_overview = build_script_formula_overview(run_root)
    except ScriptFormulaOverviewError:
        script_formula_overview = {"schemaVersion": 1, "status": "unavailable", "gaps": [{"code": "script_formula_overview_unavailable"}]}
    try:
        highlight_overview = build_highlight_overview(run_root)
    except HighlightOverviewError:
        highlight_overview = {
            "schemaVersion": 1,
            "status": "unavailable",
            "source": {"materialCount": 0, "verifiedFrameCount": 0},
            "cards": [],
            "gaps": [{"code": "highlight_overview_unavailable"}],
        }
    return {
        "schemaVersion": SCHEMA_VERSION,
        "kind": OVERVIEW_KIND,
        "runId": _nonblank(summary["runId"], "run summary runId"),
        "source": {
            "path": relative_path,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "recordCount": len(rows),
        },
        "queryContext": _query_context(run_root),
        "fields": fields,
        "defaultFieldIds": default_ids,
        "rows": rows,
        "audienceOverview": audience_overview,
        "scriptFormulaOverview": script_formula_overview,
        "highlightOverview": highlight_overview,
    }


def _json_for_script(model: dict) -> str:
    return json.dumps(model, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


def render_overview_html(model: dict) -> str:
    embedded = _json_for_script(model)
    return r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>云图素材榜单数据工作台</title>
<style>
:root { color-scheme: light; --bg:#f4f7fb; --surface:#fff; --muted:#66748b; --text:#172033; --line:#dfe6f0; --line-strong:#c9d5e5; --accent:#2563eb; --accent-soft:#eff6ff; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; color:var(--text); background:var(--bg); }
* { box-sizing:border-box; }
body { margin:0; padding:32px; background:var(--bg); }
main { max-width:1120px; margin:0 auto; }
h1 { margin:0 0 22px; font-size:30px; line-height:1.25; letter-spacing:-.02em; }
.toolbar,.summary,.pager { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.toolbar { padding:14px; background:var(--surface); border:1px solid var(--line); border-radius:14px; box-shadow:0 8px 24px rgba(34,64,112,.06); }
input[type=search] { min-width:300px; flex:1; height:44px; padding:10px 13px; border:1px solid var(--line-strong); border-radius:9px; background:var(--surface); color:var(--text); font-size:15px; outline:none; }
input[type=search]:focus { border-color:var(--accent); box-shadow:0 0 0 3px rgba(37,99,235,.14); }
button { min-height:40px; padding:8px 14px; border:1px solid var(--line-strong); border-radius:9px; background:var(--surface); color:var(--text); cursor:pointer; font-size:14px; }
button:hover:not(:disabled) { border-color:var(--accent); background:var(--accent-soft); }
button:focus-visible,input:focus-visible { outline:3px solid rgba(37,99,235,.24); outline-offset:2px; }
button:disabled { cursor:default; opacity:.45; }
.summary { margin:18px 2px 10px; color:var(--muted); font-size:14px; }
.report-nav { display:flex; gap:8px; margin:0 0 18px; padding:5px; background:var(--surface); border:1px solid var(--line); border-radius:12px; }
.report-nav button.active { border-color:var(--accent); background:var(--accent-soft); color:#1d4ed8; font-weight:650; }
.report-section[hidden] { display:none; }
.overview-card { margin:18px 0; padding:22px; background:var(--surface); border:1px solid var(--line); border-radius:14px; box-shadow:0 8px 24px rgba(34,64,112,.05); }
.overview-card h2 { margin:0 0 8px; font-size:20px; }
.overview-card p { color:var(--muted); }
.metric-card { display:inline-flex; flex-direction:column; min-width:190px; padding:16px; border:1px solid var(--line); border-radius:12px; background:#fbfdff; }
.metric-card strong { margin-top:5px; font-size:28px; font-variant-numeric:tabular-nums; }
.chart-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
.chart-panel { min-width:0; padding:16px; border:1px solid var(--line); border-radius:12px; background:#fbfdff; }
.chart-panel h3 { margin:0 0 8px; font-size:15px; }
.chart-svg { display:block; width:100%; height:auto; min-height:220px; }
.chart-target { cursor:pointer; outline:none; }
.chart-target:focus-visible { filter:drop-shadow(0 0 4px rgba(37,99,235,.75)); }
.chart-target:hover rect,.chart-target:hover circle,.chart-target:hover path,.chart-target.is-active rect,.chart-target.is-active circle,.chart-target.is-active path { filter:brightness(.9); }
.chart-label { fill:var(--muted); font-size:12px; }
.chart-value { fill:var(--text); font-size:12px; font-weight:650; }
.legend { display:grid; gap:7px; margin-top:8px; }
.legend button { display:flex; align-items:center; gap:8px; width:100%; min-height:32px; padding:5px 8px; border:0; text-align:left; background:transparent; }
.legend-swatch { width:10px; height:10px; flex:0 0 auto; border-radius:50%; }
.formula-primary { margin-top:16px; }
.formula-secondary { margin-top:16px; }
.formula-secondary-layout { display:grid; grid-template-columns:minmax(240px, .8fr) minmax(260px, 1fr); gap:22px; align-items:center; }
.tooltip { position:fixed; z-index:30; max-width:320px; padding:8px 10px; border-radius:8px; background:#172033; color:#fff; font-size:12px; pointer-events:none; box-shadow:0 8px 22px rgba(15,23,42,.2); }
.section-nav { display:flex; gap:8px; margin:0 0 16px; }
.section-nav button.active { border-color:var(--accent); background:var(--accent); color:#fff; }
[data-section-panel][hidden] { display:none; }
.audience-section { display:grid; gap:16px; }
.audience-card { width:100%; min-width:0; overflow:hidden; padding:18px; background:var(--surface); border:1px solid var(--line); border-radius:14px; box-shadow:0 8px 24px rgba(34,64,112,.06); }
.chart-card h3 { margin:0; font-size:16px; }
.chart-box { min-width:0; max-width:100%; min-height:260px; overflow-x:auto; overflow-y:hidden; }
.chart-box svg { display:block; min-width:0; max-width:100%; height:290px; }
.chart-bar,.script-formula-bar { fill:#5b8def; cursor:pointer; }
.chart-bar:hover,.chart-bar:focus,.script-formula-bar:hover,.script-formula-bar:focus { fill:#2563eb; outline:none; }
.chart-axis { stroke:#dfe6f0; stroke-width:1; }
.donut-layout { display:grid; grid-template-columns:minmax(220px,1.2fr) minmax(0,.8fr); align-items:center; gap:12px; min-height:270px; }
.donut-layout svg { width:100%; min-width:220px; max-width:100%; height:250px; }
.donut-layout .chart-box { display:flex; align-items:center; justify-content:center; min-height:250px; overflow:visible; }
.chart-grid > .chart-card { display:flex; flex-direction:column; }
.chart-grid > .chart-card .donut-layout { flex:1; }
.donut-segment { cursor:pointer; stroke:#fff; stroke-width:2; outline:none; transform-box:view-box; transform-origin:116px 124px; transition:transform .24s ease,filter .24s ease,stroke-width .24s ease; }
.donut-segment:hover,.donut-segment:focus,.donut-segment.active { filter:brightness(.9); }
.donut-center-label { fill:#63708a; font-size:12px; text-anchor:middle; }
.donut-center-value { fill:#172033; font-size:18px; font-weight:700; text-anchor:middle; }
.legend-item { display:grid; grid-template-columns:10px minmax(0,1fr); gap:7px; align-items:start; min-height:32px; padding:4px 6px; border:0; border-radius:6px; text-align:left; font-size:12px; }
.legend-item:hover,.legend-item:focus,.legend-item.active { background:var(--accent-soft); outline:none; }
.legend-detail { display:block; margin-top:2px; color:var(--muted); }
.legend-item span { min-width:0; overflow-wrap:anywhere; }
.script-section { display:grid; gap:16px; }
.script-card-header { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:8px; }
.script-card-header h3 { margin:0; }
.script-card-actions { display:flex; align-items:center; justify-content:flex-end; gap:12px; }
.script-card-hint { color:var(--muted); font-size:12px; }
.script-card-header button { min-height:34px; padding:6px 10px; }
.script-formula-svg { width:min(760px,100%); height:290px; margin:0 auto; }
.script-formula-donut { display:grid; grid-template-columns:minmax(220px,1fr) minmax(180px,1fr); align-items:center; gap:14px; }
.script-formula-donut svg { min-width:220px; height:270px; }
.script-formula-segment { transform-box:view-box; transform-origin:116px 130px; transition:transform .24s ease,filter .24s ease,stroke-width .24s ease; }
.script-formula-segment.active { filter:brightness(.9); stroke-width:3; }
.chart-tooltip { position:fixed; z-index:30; max-width:280px; padding:10px 12px; pointer-events:none; background:#172033; color:#fff; border-radius:8px; box-shadow:0 8px 24px rgba(15,23,42,.2); font-size:12px; line-height:1.65; }
.chart-tooltip[hidden] { display:none; }
.highlight-section { display:grid; gap:16px; }
.highlight-grid { display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:14px; }
.highlight-card { min-width:0; overflow:hidden; padding:12px; background:var(--surface); border:1px solid var(--line); border-radius:12px; box-shadow:0 8px 24px rgba(34,64,112,.05); }
.highlight-thumb { display:block; width:100%; aspect-ratio:9 / 16; min-height:0; padding:0; overflow:hidden; border:0; border-radius:8px; background:#e9eef6; }
.highlight-thumb img { display:block; width:100%; height:100%; object-fit:contain; }
.highlight-thumb:focus-visible { outline:3px solid rgba(37,99,235,.35); outline-offset:2px; }
.highlight-conditions,.highlight-values { display:flex; flex-direction:column; align-items:center; justify-content:center; width:100%; min-width:0; text-align:center; }
.highlight-conditions { gap:2px; min-height:18px; margin:8px 0 4px; }
.highlight-values { gap:2px; min-height:18px; margin:0 0 10px; }
.highlight-condition,.highlight-value { display:block; width:100%; min-width:0; overflow:hidden; text-align:center; text-overflow:ellipsis; white-space:nowrap; }
.highlight-condition { color:var(--text); font-size:12px; font-weight:600; line-height:1.35; }
.highlight-value { color:var(--muted); font-size:12px; line-height:1.35; }
.highlight-material { display:block; width:100%; min-width:0; padding:4px 0; color:#1d4ed8; cursor:pointer; font-size:12px; line-height:1.4; text-align:center; text-decoration:underline; text-decoration-thickness:1px; text-underline-offset:2px; white-space:normal; overflow-wrap:anywhere; word-break:break-word; }
.highlight-material:focus-visible { outline:3px solid rgba(37,99,235,.24); outline-offset:2px; border-radius:4px; }
.highlight-modal[hidden] { display:none; }
.highlight-modal { position:fixed; inset:0; z-index:40; display:grid; place-items:center; padding:24px; }
.highlight-modal-backdrop { position:absolute; inset:0; background:rgba(15,23,42,.72); }
.highlight-modal-panel { position:relative; display:flex; flex-direction:column; align-items:center; width:min(960px,100%); max-height:calc(100vh - 48px); padding:18px; border-radius:16px; background:var(--surface); box-shadow:0 24px 70px rgba(15,23,42,.35); }
.highlight-modal-close { align-self:flex-end; min-width:36px; min-height:36px; padding:0; border:0; border-radius:50%; color:var(--muted); font-size:24px; }
.highlight-modal-image { display:block; max-width:100%; max-height:calc(100vh - 150px); object-fit:contain; border-radius:10px; background:#0f172a; }
.highlight-modal-caption { margin:12px 0 0; color:var(--muted); font-size:13px; text-align:center; }
.table-wrap { overflow:auto; background:var(--surface); border:1px solid var(--line); border-radius:14px; box-shadow:0 8px 24px rgba(34,64,112,.05); }
table { width:100%; min-width:980px; border-collapse:separate; border-spacing:0; }
th,td { padding:14px 16px; border-bottom:1px solid var(--line); text-align:left; white-space:nowrap; vertical-align:middle; }
th { position:sticky; top:0; z-index:2; background:#f8fafc; color:#45546b; font-size:13px; font-weight:650; }
th button { min-height:30px; padding:4px 7px; border:0; background:transparent; color:inherit; font:inherit; }
tbody tr:last-child td { border-bottom:0; }
tbody tr:hover td { background:#fbfdff; }
.material-name-column { position:sticky; left:0; z-index:1; min-width:380px; width:380px; background:var(--surface); box-shadow:8px 0 14px -14px rgba(23,32,51,.65); }
th.material-name-column { z-index:4; background:#f8fafc; }
tbody tr:hover .material-name-column { background:#fbfdff; }
.material-title { max-width:350px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; font-weight:520; }
.material-id { margin-top:5px; color:var(--muted); font-size:12px; font-variant-numeric:tabular-nums; }
mark { padding:0 2px; background:#fff0a8; border-radius:3px; }
.empty { padding:44px; text-align:center; color:var(--muted); }
.pager { justify-content:space-between; padding:14px 2px; color:var(--muted); font-size:14px; }
.pager button { min-height:34px; padding:5px 10px; }
body.modal-open { overflow:hidden; }
.field-modal[hidden] { display:none; }
.field-modal { position:fixed; inset:0; z-index:20; display:grid; place-items:center; padding:24px; }
.field-modal-backdrop { position:absolute; inset:0; background:rgba(15,23,42,.42); backdrop-filter:blur(2px); }
.field-modal-panel { position:relative; display:flex; flex-direction:column; width:min(1180px,100%); height:min(760px,calc(100vh - 48px)); overflow:hidden; background:var(--surface); border:1px solid var(--line); border-radius:16px; box-shadow:0 24px 70px rgba(15,23,42,.24); }
.field-modal-header { display:flex; align-items:flex-start; justify-content:space-between; gap:20px; padding:22px 24px 16px; border-bottom:1px solid var(--line); }
.field-modal-header h2 { margin:0; font-size:20px; }
.field-modal-header p { margin:6px 0 0; color:var(--muted); font-size:13px; }
.field-modal-close { min-width:36px; min-height:36px; padding:0; border:0; border-radius:50%; color:var(--muted); font-size:24px; }
.field-modal-body { display:grid; grid-template-columns:190px minmax(0,1fr) 290px; flex:1; min-height:0; }
.field-modal-groups { min-width:0; padding:14px 10px; overflow:auto; background:#f8fafc; border-right:1px solid var(--line); }
.field-modal-groups button { display:flex; justify-content:space-between; width:100%; min-height:38px; margin-bottom:4px; padding:8px 10px; border:0; color:#45546b; text-align:left; }
.field-modal-groups button.active { background:var(--accent-soft); color:#1d4ed8; font-weight:650; box-shadow:inset 3px 0 0 var(--accent); }
.field-modal-main { display:flex; flex-direction:column; min-width:0; min-height:0; }
.field-modal-search { padding:14px 20px; border-bottom:1px solid var(--line); }
.field-modal-search input { width:100%; min-width:0; height:40px; padding:8px 12px; border:1px solid var(--line-strong); border-radius:8px; font-size:14px; }
.field-options { min-height:0; overflow:auto; padding:18px 22px 24px; }
.field-option-section + .field-option-section { margin-top:22px; }
.field-option-section h3 { margin:0 0 10px; font-size:14px; color:#263752; }
.field-option-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px 12px; }
.field-option { display:flex; align-items:flex-start; gap:9px; min-height:40px; padding:9px 10px; border:1px solid transparent; border-radius:8px; color:#34445e; font-size:14px; cursor:pointer; }
.field-option:hover { background:#f8fafc; border-color:#e6ebf3; }
.field-option input { width:16px; height:16px; margin:1px 0 0; accent-color:var(--accent); }
.field-modal-selected { display:flex; flex-direction:column; min-width:0; min-height:0; background:#fbfcfe; border-left:1px solid var(--line); }
.field-modal-selected-header { display:flex; align-items:center; justify-content:space-between; padding:16px 16px 12px; border-bottom:1px solid var(--line); }
.field-modal-selected-header span { color:var(--muted); font-size:12px; }
.field-modal-selected-header button { min-height:28px; padding:4px 8px; border:0; color:var(--accent); font-size:12px; }
.field-modal-selected-list { min-height:0; margin:0; padding:12px; overflow:auto; list-style:none; }
.field-modal-selected-item { display:flex; align-items:center; gap:8px; min-height:38px; margin-bottom:7px; padding:7px 8px; background:#f1f3f7; border-radius:7px; color:#34445e; font-size:13px; }
.field-modal-selected-item .field-drag-handle { color:#8a96a8; }
.field-modal-selected-item button { min-width:24px; min-height:24px; margin-left:auto; padding:0; border:0; color:var(--muted); }
.field-required { margin-left:auto; color:var(--accent); font-size:12px; }
.field-modal-footer { display:flex; align-items:center; justify-content:space-between; gap:16px; padding:14px 24px; border-top:1px solid var(--line); }
.field-modal-footer p { margin:0; color:var(--muted); font-size:12px; }
.field-modal-footer-actions { display:flex; gap:8px; }
.field-modal-footer .primary { border-color:var(--accent); background:var(--accent); color:#fff; }
@media (max-width:900px) { .field-modal-body { grid-template-columns:160px minmax(0,1fr); } .field-modal-selected { grid-column:2; max-height:190px; border-top:1px solid var(--line); } }
@media (max-width:900px) { .highlight-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } }
@media (max-width:700px) { body { padding:18px 12px; } h1 { font-size:24px; } input[type=search] { min-width:0; } .field-modal { padding:10px; } .field-modal-panel { height:calc(100vh - 20px); } .field-modal-body { display:flex; flex-direction:column; } .field-modal-groups { display:flex; gap:6px; padding:10px; overflow-x:auto; border-right:0; border-bottom:1px solid var(--line); } .field-modal-groups button { flex:0 0 auto; width:auto; margin:0; white-space:nowrap; } .field-modal-selected { max-height:190px; border-top:1px solid var(--line); border-left:0; } .field-option-grid { grid-template-columns:1fr; } .field-modal-footer { align-items:flex-end; flex-direction:column; } .field-modal-footer-actions { width:100%; } .field-modal-footer-actions button { flex:1; } .field-modal-footer p { align-self:flex-start; } .material-name-column { min-width:300px; width:300px; } .chart-grid,.donut-layout,.script-formula-donut { grid-template-columns:1fr; } .donut-layout svg,.script-formula-donut svg { margin:0 auto; } .section-nav { overflow:auto; } .section-nav button { flex:0 0 auto; } .highlight-grid { grid-template-columns:repeat(2,minmax(0,1fr)); } .highlight-modal { padding:10px; } .highlight-modal-panel { max-height:calc(100vh - 20px); padding:10px; } }
</style>
</head>
<body>
<main>
<h1>云图素材榜单数据工作台</h1>
<nav class="section-nav" aria-label="报告部分"><button type="button" data-section="materials" class="active">素材榜单</button><button type="button" data-section="audience">人群数据</button><button type="button" data-section="scripts">脚本内容公式</button><button type="button" data-section="highlights">高光帧数据</button></nav>
<section id="materials-panel" class="report-section" data-section-panel="materials">
<div class="toolbar"><input id="search" type="search" placeholder="输入素材标题或 ID" aria-label="输入素材标题或 ID"><button id="field-button" type="button">自定义指标</button></div>
<section id="field-management" class="field-modal" role="dialog" aria-modal="true" aria-labelledby="field-management-title" hidden>
  <div class="field-modal-backdrop" data-field-action="cancel"></div>
  <div class="field-modal-panel">
    <header class="field-modal-header"><div><h2 id="field-management-title">自定义指标</h2><p>选择后按固定字段分组顺序呈现表格列</p></div><button class="field-modal-close" type="button" data-field-action="cancel" aria-label="关闭自定义指标">×</button></header>
    <div class="field-modal-body"><nav id="field-groups" class="field-modal-groups" aria-label="字段分组"></nav><section class="field-modal-main" aria-label="可选指标"><div class="field-modal-search"><input id="field-search" type="search" placeholder="搜索指标" aria-label="搜索指标"></div><div id="field-options" class="field-options"></div></section><aside class="field-modal-selected" aria-label="已选择指标"><div class="field-modal-selected-header"><div><strong>已选择</strong> <span id="selected-count"></span></div><button type="button" data-field-action="reset">重置</button></div><ol id="selected-fields" class="field-modal-selected-list"></ol></aside></div>
    <footer class="field-modal-footer"><p>视频标题为固定列，素材 ID 显示在标题下方</p><div class="field-modal-footer-actions"><button type="button" data-field-action="cancel">取消</button><button class="primary" type="button" data-field-action="confirm">确定</button></div></footer>
  </div>
</section>
<section id="summary" class="summary"></section><div id="table-container" class="table-wrap"></div>
<div class="pager"><span id="range"></span><span><button id="first" type="button">首</button><button id="previous" type="button">前</button><span id="pages"></span><button id="next" type="button">后</button><button id="last" type="button">末</button></span></div>
</section>
<section id="audience-panel" class="audience-section" data-section-panel="audience" hidden>
  <div id="audience-unavailable" class="audience-card empty" hidden>人群数据不可用</div>
  <div id="audience-content">
    <div class="audience-card chart-card"><h3>八大人群分布</h3><div id="audience-eight-groups" class="chart-box"></div></div>
    <div class="chart-grid">
      <div class="audience-card chart-card"><h3>性别分布</h3><div class="donut-layout"><div id="audience-gender" class="chart-box"></div><div id="legend-gender" class="legend" aria-label="性别图例"></div></div></div>
      <div class="audience-card chart-card"><h3>年龄分布</h3><div class="donut-layout"><div id="audience-age" class="chart-box"></div><div id="legend-age" class="legend" aria-label="年龄图例"></div></div></div>
    </div>
  </div>
</section>
<section id="scripts-panel" class="script-section" data-section-panel="scripts" hidden>
  <div class="audience-card chart-card" data-script-formula-card>
    <div class="script-card-header"><h3 id="script-formula-title">一级内容公式</h3><div class="script-card-actions"><span id="script-formula-hint" class="script-card-hint">点击一级内容公式柱状图可以显示二级内容公式分布</span></div></div>
    <div id="script-formula-chart" class="chart-box"></div>
  </div>
  <div id="script-formula-secondary-card" class="audience-card chart-card" hidden>
    <div class="script-card-header"><h3 id="script-formula-secondary-title">二级内容公式分布</h3><div class="script-card-actions"><button id="script-formula-secondary-back" type="button">收起二级内容公式</button></div></div>
    <div class="script-formula-donut"><div id="script-formula-secondary-chart" class="chart-box"></div><div id="script-formula-secondary-legend" class="legend" aria-label="二级内容公式图例"></div></div>
  </div>
</section>
<section id="highlights-panel" class="highlight-section" data-section-panel="highlights" hidden>
  <div id="highlight-unavailable" class="audience-card empty" hidden>高光帧数据不可用</div>
  <div id="highlight-content">
    <div id="highlight-grid" class="highlight-grid"></div>
    <div class="pager"><span id="highlight-range"></span><span><button id="highlight-first" type="button">首</button><button id="highlight-previous" type="button">前</button><span id="highlight-pages"></span><button id="highlight-next" type="button">后</button><button id="highlight-last" type="button">末</button></span></div>
  </div>
</section>
<section id="highlight-modal" class="highlight-modal" role="dialog" aria-modal="true" aria-labelledby="highlight-modal-caption" hidden>
  <div class="highlight-modal-backdrop" data-highlight-action="close"></div>
  <div class="highlight-modal-panel">
    <button id="highlight-modal-close" class="highlight-modal-close" type="button" data-highlight-action="close" aria-label="关闭高光帧大图">×</button>
    <img id="highlight-modal-image" class="highlight-modal-image" alt="">
    <p id="highlight-modal-caption" class="highlight-modal-caption"></p>
  </div>
</section>
<div id="chart-tooltip" class="chart-tooltip" role="status" aria-live="polite" hidden></div>
</main>
<script id="overview-model" type="application/json">''' + embedded + r'''</script>
<script>
(() => {
  const model = JSON.parse(document.getElementById("overview-model").textContent);
  const pageSize = 10;
  const highlightPageSize = 12;
  const storageKey = `yuntu-overview:${model.runId}:v${model.schemaVersion}`;
  const fieldGroupOrder = ["素材基础信息", "内容曝光与播放", "点击与转化", "互动指标"];
  const presentationFields = model.fields.filter(field => field.id !== "material_id");
  const fieldRank = Object.fromEntries(presentationFields.map((field, index) => [field.id, index]));
  const groupRank = Object.fromEntries(fieldGroupOrder.map((group, index) => [group, index]));
  const orderedFields = [...presentationFields].sort((left, right) => (groupRank[left.group] ?? 99) - (groupRank[right.group] ?? 99) || fieldRank[left.id] - fieldRank[right.id]);
  const fieldMap = Object.fromEntries(orderedFields.map(field => [field.id, field]));
  const groupNames = fieldGroupOrder.filter(group => orderedFields.some(field => field.group === group));
  const requiredFieldIds = ["title"].filter(id => fieldMap[id]);
  const defaultFieldIds = Array.isArray(model.defaultFieldIds) ? model.defaultFieldIds : requiredFieldIds;
  const initialSort = model.queryContext.materialList && model.queryContext.materialList.sort || {};
  const state = { query: "", exactMaterialId: null, pendingMaterialId: null, visibleFieldIds: [], draftFieldIds: null, fieldSearch: "", activeFieldGroup: groupNames[0] || "", sort: { field: initialSort.field || null, direction: initialSort.direction || "none" }, page: 1 };
  const search = document.getElementById("search"), modal = document.getElementById("field-management"), fieldGroups = document.getElementById("field-groups"), fieldSearch = document.getElementById("field-search"), fieldOptions = document.getElementById("field-options"), selectedFields = document.getElementById("selected-fields"), selectedCount = document.getElementById("selected-count"), tableContainer = document.getElementById("table-container");
  const highlightModal = document.getElementById("highlight-modal"), highlightModalImage = document.getElementById("highlight-modal-image"), highlightModalCaption = document.getElementById("highlight-modal-caption"), highlightGrid = document.getElementById("highlight-grid");
  function normalize(value) { return String(value == null ? "" : value).normalize("NFKC").toLocaleLowerCase().trim(); }
  function orderedVisibleFieldIds(ids) { const selected = new Set(Array.isArray(ids) ? ids : []); requiredFieldIds.forEach(id => selected.add(id)); return orderedFields.filter(field => selected.has(field.id)).map(field => field.id); }
  function missing(value) { return value == null || value === ""; }
  function loadVisibleFields() { try { const stored = JSON.parse(localStorage.getItem(storageKey) || "null"); state.visibleFieldIds = orderedVisibleFieldIds(Array.isArray(stored) ? stored : defaultFieldIds); } catch (_) { state.visibleFieldIds = orderedVisibleFieldIds(defaultFieldIds); } }
  function saveVisibleFields() { try { localStorage.setItem(storageKey, JSON.stringify(state.visibleFieldIds)); } catch (_) {} }
  function escaped(value) { return String(value == null ? "" : value).replace(/[&<>"']/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;"}[char])); }
  const chartTooltip = document.getElementById("chart-tooltip");
  const audience = model.audienceOverview || {status: "unavailable"};
  const scriptFormula = model.scriptFormulaOverview || {status: "unavailable"};
  const highlightOverview = model.highlightOverview || {status: "unavailable", cards: []};
  const colors = ["#2563eb", "#60a5fa", "#14b8a6", "#f59e0b", "#ef6a6a", "#8b5cf6", "#64748b", "#22c55e"];
  const audienceState = {donutSelection: {gender: null, age: null}};
  const scriptFormulaState = {selectedPrimary: null, selectedSecondary: null};
  const highlightState = {page: 1, lastFocused: null};
  function hideChartTooltip() { chartTooltip.hidden = true; }
  function showChartTooltip(event, bucket, level, total) { const source = event.currentTarget || event.target; const rect = source && source.getBoundingClientRect ? source.getBoundingClientRect() : null; chartTooltip.innerHTML = `<div>${escaped(level)}：${escaped(bucket.label)}</div><div>覆盖素材数：${escaped(bucket.value)}</div><div>占比：${escaped(new Intl.NumberFormat("zh-CN", {style:"percent", maximumFractionDigits:2}).format(bucket.share))}</div><div>当前维度标签覆盖总和：${escaped(total)}</div>`; chartTooltip.hidden = false; chartTooltip.style.left = `${Math.min(Math.max(12, rect ? rect.right + 8 : 16), Math.max(12, window.innerWidth - chartTooltip.offsetWidth - 12))}px`; chartTooltip.style.top = `${Math.min(Math.max(12, rect ? rect.top : 16), Math.max(12, window.innerHeight - chartTooltip.offsetHeight - 12))}px`; }
  function attachChartInteractions(container, buckets, level, total, dimension) { container.querySelectorAll("[data-chart-index]").forEach(element => { const bucket = buckets[Number(element.dataset.chartIndex)]; element.addEventListener("pointerenter", event => showChartTooltip(event, bucket, level, total)); element.addEventListener("pointerleave", hideChartTooltip); element.addEventListener("focus", event => showChartTooltip(event, bucket, level, total)); element.addEventListener("blur", hideChartTooltip); if (dimension) element.addEventListener("click", event => toggleDonutSelection(dimension, event.currentTarget.dataset.chartIndex)); }); }
  function setDonutSelection(dimension, index) { audienceState.donutSelection[dimension] = index == null ? null : Number(index); document.querySelectorAll(`[data-donut-dimension="${dimension}"]`).forEach(element => { const selected = Number(element.dataset.chartIndex) === audienceState.donutSelection[dimension]; element.classList.toggle("active", selected); element.setAttribute("aria-pressed", String(selected)); if (element.classList.contains("donut-segment")) { const angle = Number(element.dataset.donutAngle || 0); const distance = selected ? 8 : 0; element.style.transform = `translate(${(Math.cos(angle) * distance).toFixed(2)}px,${(Math.sin(angle) * distance).toFixed(2)}px)`; } }); }
  function toggleDonutSelection(dimension, index) { setDonutSelection(dimension, audienceState.donutSelection[dimension] === Number(index) ? null : Number(index)); }
  function chartEmpty(label) { return `<div class="empty">暂无可验证的${escaped(label)}数据</div>`; }
  function renderBars(containerId, buckets, label, total) { const container = document.getElementById(containerId); if (!buckets.length) { container.innerHTML = chartEmpty(label); return; } const width = Math.max(760, (container.clientWidth || 900) - 8), height = 290, left = 42, bottom = 72, plotHeight = height - bottom - 20, max = Math.max(...buckets.map(item => Number(item.value)), 1), band = (width - left - 18) / buckets.length; const bars = buckets.map((bucket, index) => { const barHeight = Math.max(2, Number(bucket.value) / max * plotHeight), barWidth = band * .52, x = left + index * band + (band - barWidth) / 2, y = height - bottom - barHeight, center = x + barWidth / 2, shortLabel = bucket.label.length > 8 ? `${bucket.label.slice(0,8)}…` : bucket.label; return `<rect class="chart-bar" data-chart-index="${index}" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${barWidth.toFixed(2)}" height="${barHeight.toFixed(2)}" rx="5" tabindex="0" role="img" aria-label="${escaped(bucket.label)}，覆盖${escaped(bucket.value)}个素材，占比${escaped(new Intl.NumberFormat("zh-CN", {style:"percent", maximumFractionDigits:2}).format(bucket.share))}"></rect><text class="chart-value" x="${center.toFixed(2)}" y="${Math.max(14,y-6).toFixed(2)}" text-anchor="middle">${escaped(bucket.value)}</text><text class="chart-label" x="${center.toFixed(2)}" y="${height-42}" text-anchor="middle">${escaped(shortLabel)}</text>`; }).join(""); container.innerHTML = `<svg style="width:100%;height:${height}px" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="group" aria-label="${escaped(label)}柱状图"><line class="chart-axis" x1="${left}" y1="${height-bottom}" x2="${width-12}" y2="${height-bottom}"></line>${bars}</svg>`; attachChartInteractions(container, buckets, label, total, null); }
  function donutPath(start, end, outer, inner, cx, cy) { const point = (radius, angle) => `${(cx + radius * Math.cos(angle)).toFixed(2)} ${(cy + radius * Math.sin(angle)).toFixed(2)}`; const sweep = end - start, full = Math.PI * 2; if (sweep >= full - .0001) { const midpoint = start + Math.PI; return `M ${point(outer,start)} A ${outer} ${outer} 0 1 1 ${point(outer,midpoint)} A ${outer} ${outer} 0 1 1 ${point(outer,start)} L ${point(inner,start)} A ${inner} ${inner} 0 1 0 ${point(inner,midpoint)} A ${inner} ${inner} 0 1 0 ${point(inner,start)} Z`; } const large = sweep > Math.PI ? 1 : 0; return `M ${point(outer,start)} A ${outer} ${outer} 0 ${large} 1 ${point(outer,end)} L ${point(inner,end)} A ${inner} ${inner} 0 ${large} 0 ${point(inner,start)} Z`; }
  function renderDonut(containerId, legendId, buckets, label, dimension) { const container = document.getElementById(containerId), legend = document.getElementById(legendId); if (!buckets.length) { container.innerHTML = chartEmpty(label); legend.innerHTML = ""; return; } const total = buckets[0].total || buckets.reduce((sum, item) => sum + item.value, 0); let cursor = -Math.PI / 2; const segments = buckets.map((bucket, index) => { const end = cursor + bucket.value / total * Math.PI * 2, angle = (cursor + end) / 2, path = donutPath(cursor, end, 92, 56, 116, 124); cursor = end; return `<path class="donut-segment" data-donut-dimension="${dimension}" data-chart-index="${index}" data-donut-angle="${angle.toFixed(6)}" d="${path}" fill="${colors[index % colors.length]}" tabindex="0" role="img" aria-pressed="false" aria-label="${escaped(bucket.label)}，覆盖${escaped(bucket.value)}个素材，占比${escaped(new Intl.NumberFormat("zh-CN", {style:"percent", maximumFractionDigits:2}).format(bucket.share))}"></path>`; }).join(""); container.innerHTML = `<svg viewBox="0 0 232 250" role="group" aria-label="${escaped(label)}环形图">${segments}<text class="donut-center-label" x="116" y="118">覆盖素材数</text><text class="donut-center-value" x="116" y="143">${escaped(total)}</text></svg>`; legend.innerHTML = buckets.map((bucket, index) => `<button type="button" class="legend-item" data-donut-dimension="${dimension}" data-chart-index="${index}" tabindex="0" role="img" aria-pressed="false" aria-label="${escaped(bucket.label)}，覆盖${escaped(bucket.value)}个素材，占比${escaped(new Intl.NumberFormat("zh-CN", {style:"percent", maximumFractionDigits:2}).format(bucket.share))}"><span class="legend-swatch" style="background:${colors[index % colors.length]}"></span><span>${escaped(bucket.label)}<span class="legend-detail">${escaped(bucket.value)} 个素材 · ${new Intl.NumberFormat("zh-CN", {style:"percent", maximumFractionDigits:2}).format(bucket.share)}</span></span></button>`).join(""); attachChartInteractions(container, buckets, label, total, dimension); attachChartInteractions(legend, buckets, label, total, dimension); setDonutSelection(dimension, audienceState.donutSelection[dimension]); }
  function renderAudience() { const content = document.getElementById("audience-content"), unavailable = document.getElementById("audience-unavailable"), available = audience.status === "available"; content.hidden = !available; unavailable.hidden = available; if (!available) return; const dimensions = audience.dimensions || {}; const crowd = dimensions.crowd_group || {buckets:[], total:0}, gender = dimensions.gender || {buckets:[], total:0}, age = dimensions.age || {buckets:[], total:0}; renderBars("audience-eight-groups", crowd.buckets, "八大人群", crowd.total); renderDonut("audience-gender", "legend-gender", gender.buckets, "性别", "gender"); renderDonut("audience-age", "legend-age", age.buckets, "年龄", "age"); }
  function formulaShare(bucket) { return new Intl.NumberFormat("zh-CN", {style:"percent", maximumFractionDigits:2}).format(bucket.share); }
  function setScriptFormulaSelection(index) { scriptFormulaState.selectedSecondary = index == null ? null : Number(index); document.querySelectorAll("[data-script-formula-secondary-index]").forEach(item => { const selected = Number(item.dataset.scriptFormulaSecondaryIndex) === scriptFormulaState.selectedSecondary; item.classList.toggle("active", selected); item.setAttribute("aria-pressed", String(selected)); if (item.classList.contains("script-formula-segment")) { const angle = Number(item.dataset.scriptFormulaAngle || 0); const distance = selected ? 8 : 0; item.style.transform = `translate(${(Math.cos(angle) * distance).toFixed(2)}px,${(Math.sin(angle) * distance).toFixed(2)}px)`; } }); }
  function attachScriptFormulaInteractions(container, buckets, level, total) { container.querySelectorAll("[data-script-formula-index],[data-script-formula-secondary-index]").forEach(element => { const index = Number(element.dataset.scriptFormulaSecondaryIndex ?? element.dataset.scriptFormulaIndex), bucket = buckets[index]; element.addEventListener("pointerenter", event => showChartTooltip(event, bucket, level, total)); element.addEventListener("pointerleave", hideChartTooltip); element.addEventListener("focus", event => showChartTooltip(event, bucket, level, total)); element.addEventListener("blur", hideChartTooltip); if (level === "二级内容公式") element.addEventListener("click", () => setScriptFormulaSelection(scriptFormulaState.selectedSecondary === index ? null : index)); }); }
  function renderScriptFormula() { const chart = document.getElementById("script-formula-chart"), secondaryCard = document.getElementById("script-formula-secondary-card"), secondaryChart = document.getElementById("script-formula-secondary-chart"), secondaryLegend = document.getElementById("script-formula-secondary-legend"), secondaryTitle = document.getElementById("script-formula-secondary-title"), title = document.getElementById("script-formula-title"), hint = document.getElementById("script-formula-hint"); hideChartTooltip(); if (scriptFormula.status !== "available") { title.textContent = "一级内容公式"; hint.hidden = true; chart.innerHTML = '<div class="empty">脚本内容公式不可用</div>'; secondaryCard.hidden = true; return; } const primaryBuckets = Array.isArray(scriptFormula.primaryBuckets) ? scriptFormula.primaryBuckets : []; hint.hidden = false; if (!primaryBuckets.length) { chart.innerHTML = '<div class="empty">暂无可展示的一级内容公式</div>'; secondaryCard.hidden = true; return; } const width = Math.max(560, Math.min(760, primaryBuckets.length * 170, (chart.clientWidth || 900) - 8)), height = 290, left = 42, bottom = 72, plotHeight = height - bottom - 20, max = Math.max(...primaryBuckets.map(bucket => Number(bucket.value)), 1), band = (width - left - 18) / primaryBuckets.length; const bars = primaryBuckets.map((bucket, index) => { const barHeight = Math.max(2, Number(bucket.value) / max * plotHeight), barWidth = band * .52, x = left + index * band + (band - barWidth) / 2, y = height - bottom - barHeight, center = x + barWidth / 2, shortLabel = bucket.label.length > 8 ? `${bucket.label.slice(0,8)}…` : bucket.label; return `<rect class="script-formula-bar" data-script-formula-index="${index}" x="${x.toFixed(2)}" y="${y.toFixed(2)}" width="${barWidth.toFixed(2)}" height="${barHeight.toFixed(2)}" rx="5" tabindex="0" role="button" aria-label="${escaped(bucket.label)}，覆盖${escaped(bucket.value)}个素材，占比${escaped(formulaShare(bucket))}" data-script-primary="${escaped(bucket.label)}"></rect><text class="chart-value" x="${center.toFixed(2)}" y="${Math.max(14,y-6).toFixed(2)}" text-anchor="middle">${escaped(bucket.value)}</text><text class="chart-label" x="${center.toFixed(2)}" y="${height-42}" text-anchor="middle">${escaped(shortLabel)}</text>`; }).join(""); chart.innerHTML = `<svg class="script-formula-svg" style="width:${width}px;height:${height}px" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="group" aria-label="一级内容公式柱状图"><line class="chart-axis" x1="${left}" y1="${height-bottom}" x2="${width-12}" y2="${height-bottom}"></line>${bars}</svg>`; attachScriptFormulaInteractions(chart, primaryBuckets, "一级内容公式", scriptFormula.coverage.formulaMaterialCount); chart.querySelectorAll("[data-script-primary]").forEach(element => { const select = () => { scriptFormulaState.selectedPrimary = element.dataset.scriptPrimary; renderScriptFormula(); }; element.addEventListener("click", select); element.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); select(); } }); }); if (scriptFormulaState.selectedPrimary == null) { secondaryCard.hidden = true; return; } const primary = scriptFormulaState.selectedPrimary, primaryBucket = primaryBuckets.find(item => item.label === primary), secondaryBuckets = (scriptFormula.secondaryBucketsByPrimary?.[primary] || []).map(item => ({...item, total: primaryBucket ? primaryBucket.value : 0})); secondaryCard.hidden = false; secondaryTitle.textContent = `${primary} · 二级内容公式分布`; if (!secondaryBuckets.length) { secondaryChart.innerHTML = '<div class="empty">暂无该一级内容公式的二级公式数据</div>'; secondaryLegend.innerHTML = ""; return; } let cursor = -Math.PI / 2; const secondaryValueTotal = secondaryBuckets.reduce((sum, bucket) => sum + Math.max(0, Number(bucket.value) || 0), 0), segments = secondaryBuckets.map((bucket, index) => { const end = cursor + bucket.value / secondaryValueTotal * Math.PI * 2, angle = (cursor + end) / 2, path = donutPath(cursor, end, 96, 58, 116, 130); cursor = end; return `<path class="donut-segment script-formula-segment" data-script-formula-secondary-index="${index}" data-script-formula-angle="${angle.toFixed(6)}" d="${path}" fill="${colors[index % colors.length]}" tabindex="0" role="img" aria-pressed="false" aria-label="${escaped(bucket.label)}，覆盖${escaped(bucket.value)}个素材，占比${escaped(formulaShare(bucket))}"></path>`; }).join(""); secondaryChart.innerHTML = `<svg viewBox="0 0 232 270" role="group" aria-label="${escaped(primary)}二级内容公式环形图">${segments}<text class="donut-center-label" x="116" y="124">当前一级覆盖素材数</text><text class="donut-center-value" x="116" y="150">${escaped(primaryBucket ? primaryBucket.value : 0)}</text></svg>`; secondaryLegend.innerHTML = secondaryBuckets.map((bucket, index) => `<button type="button" class="legend-item" data-script-formula-secondary-index="${index}" tabindex="0" role="img" aria-pressed="false" aria-label="${escaped(bucket.label)}，覆盖${escaped(bucket.value)}个素材，占比${escaped(formulaShare(bucket))}"><span class="legend-swatch" style="background:${colors[index % colors.length]}"></span><span>${escaped(bucket.label)}<span class="legend-detail">${escaped(bucket.value)} 个素材 · ${escaped(formulaShare(bucket))}</span></span></button>`).join(""); attachScriptFormulaInteractions(secondaryChart, secondaryBuckets, "二级内容公式", primaryBucket ? primaryBucket.value : 0); attachScriptFormulaInteractions(secondaryLegend, secondaryBuckets, "二级内容公式", primaryBucket ? primaryBucket.value : 0); }
  function highlightConditionLabel(reason) { if (reason.type === "cover") return "封面画面"; const kind = reason.type === "top_values" ? "数值" : "波峰"; return `${reason.trend_name}${kind}Top${reason.rank}`; }
  function highlightValueLabel(second, reason) { if (reason.type === "cover") return ""; const value = new Intl.NumberFormat("zh-CN", {maximumFractionDigits:4}).format(Number(reason.value)); return `${second}s · ${reason.trend_name} ${value}`; }
  function highlightConditionReasons(card) { const reasons = Array.isArray(card.reasons) ? card.reasons : [], metricReasons = reasons.filter(reason => reason.type !== "cover"); return (metricReasons.length ? metricReasons : reasons).map(highlightConditionLabel).filter(Boolean); }
  function highlightValueReasons(card) { return (Array.isArray(card.reasons) ? card.reasons : []).map(reason => highlightValueLabel(card.second, reason)).filter(Boolean); }
  function highlightDescription(card) { return [...highlightConditionReasons(card), ...highlightValueReasons(card)].join(" · "); }
  function renderHighlights() { const content = document.getElementById("highlight-content"), unavailable = document.getElementById("highlight-unavailable"), cards = Array.isArray(highlightOverview.cards) ? highlightOverview.cards : [], available = highlightOverview.status === "available" && cards.length > 0; content.hidden = !available; unavailable.hidden = available; if (!available) return; const pageCount = Math.max(1, Math.ceil(cards.length / highlightPageSize)); highlightState.page = Math.min(highlightState.page, pageCount); const start = (highlightState.page - 1) * highlightPageSize, pageCards = cards.slice(start, start + highlightPageSize); highlightGrid.innerHTML = pageCards.map(card => { const conditions = highlightConditionReasons(card), values = highlightValueReasons(card), description = highlightDescription(card); return `<article class="highlight-card"><button type="button" class="highlight-thumb" data-highlight-open="${escaped(card.id)}" aria-label="查看${escaped(description)}大图"><img src="${escaped(card.assetPath)}" alt="${escaped(description)}"></button><div class="highlight-conditions" aria-label="命中筛选条件">${conditions.map(condition => `<span class="highlight-condition" title="${escaped(condition)}">${escaped(condition)}</span>`).join("")}</div><div class="highlight-values" aria-label="对应指标数值">${values.map(value => `<span class="highlight-value" title="${escaped(value)}">${escaped(value)}</span>`).join("")}</div><a href="#single-material-data" class="highlight-material" data-highlight-material-id="${escaped(card.materialId)}" title="后续定位到单素材数据：${escaped(card.materialTitle)}">查看素材：${escaped(card.materialTitle)}</a></article>`; }).join(""); document.getElementById("highlight-range").textContent = `显示 ${start + 1}-${Math.min(start + highlightPageSize, cards.length)} / ${cards.length}`; document.getElementById("highlight-pages").textContent = `${highlightState.page} / ${pageCount}`; ["highlight-first", "highlight-previous"].forEach(id => document.getElementById(id).disabled = highlightState.page <= 1); ["highlight-next", "highlight-last"].forEach(id => document.getElementById(id).disabled = highlightState.page >= pageCount); }
  function openHighlightModal(cardId, trigger) { const card = (highlightOverview.cards || []).find(item => item.id === cardId); if (!card) return; const description = highlightDescription(card); highlightState.lastFocused = trigger || document.activeElement; highlightModalImage.src = card.assetPath; highlightModalImage.alt = description; highlightModalCaption.textContent = `${card.materialTitle} · ${description}`; highlightModal.hidden = false; document.body.classList.add("modal-open"); document.getElementById("highlight-modal-close").focus(); }
  function closeHighlightModal() { highlightModal.hidden = true; highlightModalImage.removeAttribute("src"); document.body.classList.remove("modal-open"); if (highlightState.lastFocused && typeof highlightState.lastFocused.focus === "function") highlightState.lastFocused.focus(); highlightState.lastFocused = null; }
  function jumpToMaterial(materialId) { state.pendingMaterialId = materialId; window.dispatchEvent(new CustomEvent("yuntu:highlight-material", {detail: {materialId}})); }
  renderAudience(); renderScriptFormula(); renderHighlights();
  function highlighted(value) { const text = escaped(value); const query = normalize(state.query); if (!query) return text; const pattern = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "giu"); return text.replace(pattern, match => `<mark>${match}</mark>`); }
  function display(value, field) { if (missing(value)) return "—"; if (field.id === "video_duration") return `${escaped(value)} 秒`; if (field.valueType === "rate") return `${new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 2}).format(Number(value) * 100)}%`; if (field.valueType === "number") return new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 2}).format(Number(value)); if (field.valueType === "list") return escaped(value.join("、")); if (field.valueType === "date") { const raw = String(value); return escaped(raw.length === 8 ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6)}` : raw); } return escaped(value); }
  function compareValues(left, right, field) { const leftMissing = missing(left), rightMissing = missing(right); if (leftMissing || rightMissing) return leftMissing === rightMissing ? 0 : (leftMissing ? 1 : -1); if (field.valueType === "number" || field.valueType === "rate") return Number(left) - Number(right); if (field.valueType === "date") return String(left).localeCompare(String(right)); return normalize(left).localeCompare(normalize(right)); }
  function compareRows(left, right) { const field = fieldMap[state.sort.field]; if (missing(left.values[field.id]) || missing(right.values[field.id])) return compareValues(left.values[field.id], right.values[field.id], field); const result = compareValues(left.values[field.id], right.values[field.id], field); if (result) return state.sort.direction === "desc" ? -result : result; const rank = compareValues(left.values.rank, right.values.rank, {valueType: "number"}); if (rank) return rank; return normalize(left.materialId).localeCompare(normalize(right.materialId)); }
  function matchingRows() { const query = normalize(state.query); const rows = state.exactMaterialId ? model.rows.filter(row => row.materialId === state.exactMaterialId) : model.rows.filter(row => !query || normalize(row.materialId).includes(query) || normalize(row.values.title).includes(query)); if (state.sort.field && state.sort.direction !== "none" && fieldMap[state.sort.field] && fieldMap[state.sort.field].sortable) rows.sort(compareRows); return rows; }
  function renderFieldDialog() { state.draftFieldIds = orderedVisibleFieldIds(state.draftFieldIds || state.visibleFieldIds); fieldGroups.innerHTML = groupNames.map(group => `<button type="button" class="${!state.fieldSearch && state.activeFieldGroup === group ? "active" : ""}" data-field-group="${escaped(group)}">${escaped(group)}<span>${orderedFields.filter(field => field.group === group).length}</span></button>`).join(""); const query = normalize(state.fieldSearch); const available = query ? orderedFields.filter(field => normalize(field.label).includes(query) || normalize(field.id).includes(query)) : orderedFields.filter(field => field.group === state.activeFieldGroup); const grouped = {}; available.forEach(field => (grouped[field.group] ||= []).push(field)); fieldOptions.innerHTML = Object.entries(grouped).map(([group, fields]) => `<section class="field-option-section"><h3>${escaped(group)}</h3><div class="field-option-grid">${fields.map(field => `<label class="field-option"><input type="checkbox" data-field-id="${escaped(field.id)}"${state.draftFieldIds.includes(field.id) ? " checked" : ""}${requiredFieldIds.includes(field.id) ? " disabled" : ""}><span>${escaped(field.label)}</span></label>`).join("")}</div></section>`).join("") || '<div class="empty">没有匹配字段</div>'; const selected = state.draftFieldIds.map(id => fieldMap[id]).filter(Boolean); selectedCount.textContent = `（${selected.length}）`; selectedFields.innerHTML = selected.map(field => `<li class="field-modal-selected-item"><span class="field-drag-handle">☷</span><span>${escaped(field.label)}</span>${requiredFieldIds.includes(field.id) ? '<span class="field-required">固定</span>' : `<button type="button" data-remove-field-id="${escaped(field.id)}" aria-label="移除${escaped(field.label)}">×</button>`}</li>`).join(""); }
  function openFieldDialog() { state.draftFieldIds = orderedVisibleFieldIds(state.visibleFieldIds); state.fieldSearch = ""; state.activeFieldGroup = groupNames[0] || ""; fieldSearch.value = ""; modal.hidden = false; document.body.classList.add("modal-open"); renderFieldDialog(); fieldSearch.focus(); }
  function closeFieldDialog() { modal.hidden = true; state.draftFieldIds = null; state.fieldSearch = ""; document.body.classList.remove("modal-open"); }
  function confirmFieldDialog() { state.visibleFieldIds = orderedVisibleFieldIds(state.draftFieldIds); state.page = 1; saveVisibleFields(); closeFieldDialog(); render(); }
  function sortLabel(field) { if (state.sort.field !== field.id || state.sort.direction === "none") return ""; return state.sort.direction === "asc" ? " ↑" : " ↓"; }
  function renderTable(rows) { const visibleFields = orderedVisibleFieldIds(state.visibleFieldIds).map(id => fieldMap[id]).filter(Boolean); if (!rows.length) { tableContainer.innerHTML = '<div class="empty">没有匹配素材</div>'; return; } const pageCount = Math.max(1, Math.ceil(rows.length / pageSize)); state.page = Math.min(state.page, pageCount); const pageRows = rows.slice((state.page - 1) * pageSize, state.page * pageSize); const header = visibleFields.map(field => `<th scope="col" class="${field.id === "title" ? "material-name-column" : ""}">${field.sortable ? `<button type="button" data-sort-id="${escaped(field.id)}">${escaped(field.label)}${sortLabel(field)}</button>` : escaped(field.label)}</th>`).join(""); const body = pageRows.map(row => `<tr>${visibleFields.map(field => field.id === "title" ? `<td class="material-name-column"><div class="material-title">${highlighted(row.values.title)}</div><div class="material-id">素材ID：${highlighted(row.materialId)}</div></td>` : `<td>${display(row.values[field.id], field)}</td>`).join("")}</tr>`).join(""); tableContainer.innerHTML = `<table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`; tableContainer.querySelectorAll("button[data-sort-id]").forEach(button => button.addEventListener("click", event => { const field = event.currentTarget.dataset.sortId; const next = state.sort.field !== field ? "asc" : state.sort.direction === "none" ? "asc" : state.sort.direction === "asc" ? "desc" : "none"; state.sort = {field, direction: next}; state.page = 1; render(); })); }
  function renderPager(total) { const pageCount = Math.max(1, Math.ceil(total / pageSize)); state.page = Math.min(state.page, pageCount); const start = total ? (state.page - 1) * pageSize + 1 : 0; const end = Math.min(state.page * pageSize, total); document.getElementById("summary").textContent = `共 ${total} 条`; document.getElementById("range").textContent = total ? `显示 ${start}-${end} / ${total}` : "暂无记录"; document.getElementById("pages").textContent = `${state.page} / ${pageCount}`; ["first", "previous"].forEach(id => document.getElementById(id).disabled = state.page <= 1); ["next", "last"].forEach(id => document.getElementById(id).disabled = state.page >= pageCount); }
  function render() { const rows = matchingRows(); renderTable(rows); renderPager(rows.length); }
  modal.addEventListener("click", event => { const action = event.target.closest("[data-field-action]")?.dataset.fieldAction; if (action === "cancel") closeFieldDialog(); if (action === "confirm") confirmFieldDialog(); if (action === "reset") { state.draftFieldIds = orderedVisibleFieldIds(defaultFieldIds); renderFieldDialog(); } const group = event.target.closest("[data-field-group]")?.dataset.fieldGroup; if (group) { state.activeFieldGroup = group; state.fieldSearch = ""; fieldSearch.value = ""; renderFieldDialog(); } const removeId = event.target.closest("[data-remove-field-id]")?.dataset.removeFieldId; if (removeId && !requiredFieldIds.includes(removeId)) { state.draftFieldIds = orderedVisibleFieldIds(state.draftFieldIds.filter(id => id !== removeId)); renderFieldDialog(); } });
  modal.addEventListener("change", event => { const input = event.target.closest("input[data-field-id]"); if (!input) return; state.draftFieldIds = orderedVisibleFieldIds(input.checked ? [...state.draftFieldIds, input.dataset.fieldId] : state.draftFieldIds.filter(id => id !== input.dataset.fieldId)); renderFieldDialog(); });
  fieldSearch.addEventListener("input", event => { state.fieldSearch = event.target.value; renderFieldDialog(); fieldSearch.focus(); });
  highlightGrid.addEventListener("click", event => { const open = event.target.closest("[data-highlight-open]"); if (open) { openHighlightModal(open.dataset.highlightOpen, open); return; } const material = event.target.closest("[data-highlight-material-id]"); if (material) { event.preventDefault(); jumpToMaterial(material.dataset.highlightMaterialId); } });
  highlightModal.addEventListener("click", event => { if (event.target.closest("[data-highlight-action=close]")) closeHighlightModal(); });
  document.addEventListener("keydown", event => { if (event.key === "Escape" && !highlightModal.hidden) closeHighlightModal(); else if (event.key === "Escape" && !modal.hidden) closeFieldDialog(); else if (event.key === "Escape") hideChartTooltip(); });
  document.querySelectorAll("[data-section]").forEach(button => button.addEventListener("click", event => { const section = event.currentTarget.dataset.section; document.querySelectorAll("[data-section]").forEach(item => item.classList.toggle("active", item.dataset.section === section)); document.querySelectorAll("[data-section-panel]").forEach(panel => { panel.hidden = panel.dataset.sectionPanel !== section; }); if (section === "audience") renderAudience(); if (section === "scripts") renderScriptFormula(); if (section === "highlights") renderHighlights(); hideChartTooltip(); }));
  document.getElementById("script-formula-secondary-back").addEventListener("click", () => { scriptFormulaState.selectedPrimary = null; renderScriptFormula(); });
  search.addEventListener("input", event => { state.query = event.target.value; state.exactMaterialId = null; state.page = 1; render(); });
  document.getElementById("field-button").addEventListener("click", openFieldDialog);
  document.getElementById("first").addEventListener("click", () => { state.page = 1; render(); }); document.getElementById("previous").addEventListener("click", () => { state.page = Math.max(1, state.page - 1); render(); }); document.getElementById("next").addEventListener("click", () => { state.page += 1; render(); }); document.getElementById("last").addEventListener("click", () => { state.page = Math.max(1, Math.ceil(matchingRows().length / pageSize)); render(); });
  document.getElementById("highlight-first").addEventListener("click", () => { highlightState.page = 1; renderHighlights(); }); document.getElementById("highlight-previous").addEventListener("click", () => { highlightState.page = Math.max(1, highlightState.page - 1); renderHighlights(); }); document.getElementById("highlight-next").addEventListener("click", () => { highlightState.page += 1; renderHighlights(); }); document.getElementById("highlight-last").addEventListener("click", () => { highlightState.page = Math.max(1, Math.ceil((highlightOverview.cards || []).length / highlightPageSize)); renderHighlights(); });
  loadVisibleFields(); render();
})();
</script>
</body>
</html>
'''


def _write_atomic(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _safe_output_dir(run_dir: Path, output_dir: Path) -> Path:
    root = run_dir.resolve()
    target = output_dir.resolve()
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise OverviewReportError("output directory must remain inside the run") from exc
    if not relative.parts:
        raise OverviewReportError("output directory must not be the run directory")
    if relative.parts[0] in {"normalized", "raw-csv", "facts", "analysis", "config"}:
        raise OverviewReportError("output directory is reserved")
    if target.exists() and not target.is_dir():
        raise OverviewReportError("output directory is not a directory")
    return target


def write_overview(run_dir: Path, output_dir: Path, registry_path: Path) -> dict:
    model = build_overview_data(run_dir, registry_path)
    run_root = Path(run_dir).resolve()
    output_path = _safe_output_dir(run_root, Path(output_dir))
    output_path.mkdir(parents=True, exist_ok=True)
    if model.get("highlightOverview", {}).get("cards"):
        copy_verified_highlight_assets(run_root, output_path, model["highlightOverview"])
    data_path = output_path / "overview-data.json"
    html_path = output_path / "index.html"
    _write_atomic(data_path, json.dumps(model, ensure_ascii=False, indent=2) + "\n")
    try:
        _write_atomic(html_path, render_overview_html(model))
    except Exception:
        try:
            data_path.unlink()
        except OSError:
            pass
        raise
    relative_output = output_path.relative_to(run_root).as_posix()
    return {
        "status": "succeeded",
        "outputPaths": [f"{relative_output}/overview-data.json", f"{relative_output}/index.html"],
        "recordCount": model["source"]["recordCount"],
        "sourceSha256": model["source"]["sha256"],
    }
