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
main { max-width:1500px; margin:0 auto; }
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
@media (max-width:700px) { body { padding:18px 12px; } h1 { font-size:24px; } input[type=search] { min-width:0; } .field-modal { padding:10px; } .field-modal-panel { height:calc(100vh - 20px); } .field-modal-body { display:flex; flex-direction:column; } .field-modal-groups { display:flex; gap:6px; padding:10px; overflow-x:auto; border-right:0; border-bottom:1px solid var(--line); } .field-modal-groups button { flex:0 0 auto; width:auto; margin:0; white-space:nowrap; } .field-modal-selected { max-height:190px; border-top:1px solid var(--line); border-left:0; } .field-option-grid { grid-template-columns:1fr; } .field-modal-footer { align-items:flex-end; flex-direction:column; } .field-modal-footer-actions { width:100%; } .field-modal-footer-actions button { flex:1; } .field-modal-footer p { align-self:flex-start; } .material-name-column { min-width:300px; width:300px; } }
</style>
</head>
<body>
<main>
<h1>云图素材榜单数据工作台</h1>
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
</main>
<script id="overview-model" type="application/json">''' + embedded + r'''</script>
<script>
(() => {
  const model = JSON.parse(document.getElementById("overview-model").textContent);
  const pageSize = 10;
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
  const state = { query: "", visibleFieldIds: [], draftFieldIds: null, fieldSearch: "", activeFieldGroup: groupNames[0] || "", sort: { field: initialSort.field || null, direction: initialSort.direction || "none" }, page: 1 };
  const search = document.getElementById("search"), modal = document.getElementById("field-management"), fieldGroups = document.getElementById("field-groups"), fieldSearch = document.getElementById("field-search"), fieldOptions = document.getElementById("field-options"), selectedFields = document.getElementById("selected-fields"), selectedCount = document.getElementById("selected-count"), tableContainer = document.getElementById("table-container");
  function normalize(value) { return String(value == null ? "" : value).normalize("NFKC").toLocaleLowerCase().trim(); }
  function orderedVisibleFieldIds(ids) { const selected = new Set(Array.isArray(ids) ? ids : []); requiredFieldIds.forEach(id => selected.add(id)); return orderedFields.filter(field => selected.has(field.id)).map(field => field.id); }
  function missing(value) { return value == null || value === ""; }
  function loadVisibleFields() { try { const stored = JSON.parse(localStorage.getItem(storageKey) || "null"); state.visibleFieldIds = orderedVisibleFieldIds(Array.isArray(stored) ? stored : defaultFieldIds); } catch (_) { state.visibleFieldIds = orderedVisibleFieldIds(defaultFieldIds); } }
  function saveVisibleFields() { try { localStorage.setItem(storageKey, JSON.stringify(state.visibleFieldIds)); } catch (_) {} }
  function escaped(value) { return String(value == null ? "" : value).replace(/[&<>"']/g, char => ({"&":"&amp;", "<":"&lt;", ">":"&gt;", "\"":"&quot;", "'":"&#39;"}[char])); }
  function highlighted(value) { const text = escaped(value); const query = normalize(state.query); if (!query) return text; const pattern = new RegExp(query.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "giu"); return text.replace(pattern, match => `<mark>${match}</mark>`); }
  function display(value, field) { if (missing(value)) return "—"; if (field.id === "video_duration") return `${escaped(value)} 秒`; if (field.valueType === "rate") return `${new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 2}).format(Number(value) * 100)}%`; if (field.valueType === "number") return new Intl.NumberFormat("zh-CN", {maximumFractionDigits: 2}).format(Number(value)); if (field.valueType === "list") return escaped(value.join("、")); if (field.valueType === "date") { const raw = String(value); return escaped(raw.length === 8 ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6)}` : raw); } return escaped(value); }
  function compareValues(left, right, field) { const leftMissing = missing(left), rightMissing = missing(right); if (leftMissing || rightMissing) return leftMissing === rightMissing ? 0 : (leftMissing ? 1 : -1); if (field.valueType === "number" || field.valueType === "rate") return Number(left) - Number(right); if (field.valueType === "date") return String(left).localeCompare(String(right)); return normalize(left).localeCompare(normalize(right)); }
  function compareRows(left, right) { const field = fieldMap[state.sort.field]; if (missing(left.values[field.id]) || missing(right.values[field.id])) return compareValues(left.values[field.id], right.values[field.id], field); const result = compareValues(left.values[field.id], right.values[field.id], field); if (result) return state.sort.direction === "desc" ? -result : result; const rank = compareValues(left.values.rank, right.values.rank, {valueType: "number"}); if (rank) return rank; return normalize(left.materialId).localeCompare(normalize(right.materialId)); }
  function matchingRows() { const query = normalize(state.query); const rows = model.rows.filter(row => !query || normalize(row.materialId).includes(query) || normalize(row.values.title).includes(query)); if (state.sort.field && state.sort.direction !== "none" && fieldMap[state.sort.field] && fieldMap[state.sort.field].sortable) rows.sort(compareRows); return rows; }
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
  document.addEventListener("keydown", event => { if (event.key === "Escape" && !modal.hidden) closeFieldDialog(); });
  search.addEventListener("input", event => { state.query = event.target.value; state.page = 1; render(); });
  document.getElementById("field-button").addEventListener("click", openFieldDialog);
  document.getElementById("first").addEventListener("click", () => { state.page = 1; render(); }); document.getElementById("previous").addEventListener("click", () => { state.page = Math.max(1, state.page - 1); render(); }); document.getElementById("next").addEventListener("click", () => { state.page += 1; render(); }); document.getElementById("last").addEventListener("click", () => { state.page = Math.max(1, Math.ceil(matchingRows().length / pageSize)); render(); });
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
