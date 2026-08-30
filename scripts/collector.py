#!/usr/bin/env python3
"""Collect configured Yuntu rankings, details, and highlight frames."""

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

try:
    from yuntu_batch import (
        ConnectorInvoker,
        collection_status,
        fetch_batch,
        retry_failed_batch,
        retry_highlights_batch,
        retry_unresolved_batch,
    )
except ImportError:
    ConnectorInvoker = None
    collection_status = None
    fetch_batch = None
    retry_failed_batch = None
    retry_highlights_batch = None
    retry_unresolved_batch = None

try:
    from config_specs import (
        ConfigSpecError, resolve_highlight_spec, resolve_query_spec,
        query_to_rpa_params, detail_to_rpa_params, spec_fingerprint,
        write_resolved_specs,
    )
except ImportError:
    from .config_specs import (
        ConfigSpecError, resolve_highlight_spec, resolve_query_spec,
        query_to_rpa_params, detail_to_rpa_params, spec_fingerprint,
        write_resolved_specs,
    )

try:
    from fact_packages import FactPackageError, build_fact_packages
except ImportError:
    from .fact_packages import FactPackageError, build_fact_packages

try:
    from rpa_io import write_json_atomically
except ImportError:
    from .rpa_io import write_json_atomically

try:
    from analysis_facts import build_fact_index, load_selected_facts
    from analysis_prompt import build_prompt_packet
    from analysis_report import render_analysis_report
    from analysis_result import normalize_analysis_result, validate_analysis_result
    from analysis_spec import parse_analysis_spec
except ImportError:
    from .analysis_facts import build_fact_index, load_selected_facts
    from .analysis_prompt import build_prompt_packet
    from .analysis_report import render_analysis_report
    from .analysis_result import normalize_analysis_result, validate_analysis_result
    from .analysis_spec import parse_analysis_spec


LIST_FUNCTION_CODE = "rpa.conn.juliang.yt.industry.content.rankings.list"
DETAIL_FUNCTION_CODE = "rpa.conn.juliang.yt.industry.content.rankings.detail"
PLATFORM = "RPA_JULIANG_YT_ACCOUNT_PASSWORD"
DATA_SOURCE_TYPE = "rpa"
HEADERS = {"Content-Type": "application/json"}
RPA_REQUEST_TIMEOUT_SECONDS = 300
REQUIRED_ENVIRONMENT = (
    "ENV_BACKEND_HOST",
    "YUCE_AUTHORIZATION",
    "YUCE_SESSION_ID",
)
DATE_RANGE_TYPES = {"LAST_7_DAYS", "LAST_30_DAYS", "CUSTOM"}
AGE_VALUES = {
    "AGE_18_19",
    "AGE_20_23",
    "AGE_24_30",
    "AGE_31_35",
    "AGE_36_40",
    "AGE_41_45",
    "AGE_46_50",
    "AGE_51_55",
    "AGE_56_59",
    "AGE_60_PLUS",
}
GENDER_VALUES = {"MALE", "FEMALE"}
CROWD_GROUP_VALUES = {
    "TOWN_YOUTH",
    "GENZ",
    "SENIOR_MIDDLE",
    "REFINED_MOM",
    "NEW_WHITE_COLLAR",
    "URBAN_SILVER",
    "TOWN_MIDDLE_ELDER",
    "URBAN_BLUE_COLLAR",
}
RANKING_LIMIT_VALUES = {
    "EXPOSURE_TOP1000",
    "CTR_TOP1000",
    "INTERACTION_RATE_TOP1000",
    "COMPLETION_RATE_TOP1000",
}
BRAND_SCOPE_VALUES = {"ALL_INDUSTRY", "SPECIFIED_BRANDS"}
LIST_FIELDS = {
    "industry",
    "time_range_type",
    "custom_start_date",
    "custom_end_date",
    "ages",
    "genders",
    "crowd_groups",
    "brand_scope_type",
    "brands",
    "ranking_limit_type",
}
DETAIL_FIELDS = {
    "material_id",
    "date_range_type",
    "custom_start_date",
    "custom_end_date",
}
SHANGHAI_TIMEZONE = ZoneInfo("Asia/Shanghai")

BUSINESS_PARAMS_SCHEMA = {
    "schema_type": "reference_metadata",
    "title": "云图行业内容榜单分析",
    "list_fields": sorted(LIST_FIELDS),
    "detail_date_fields": [
        "date_range_type",
        "custom_start_date",
        "custom_end_date",
    ],
    "top_n": {"type": "positive integer", "default": 10},
}


class RpaConnectorError(RuntimeError):
    """Raised when the connector cannot safely complete an operation."""


def shanghai_today(now=None):
    if now is None:
        return datetime.now(SHANGHAI_TIMEZONE).date()
    return now.astimezone(SHANGHAI_TIMEZONE).date()


def runtime_config(environ=None):
    environment = os.environ if environ is None else environ
    missing = [
        name
        for name in REQUIRED_ENVIRONMENT[:2]
        if not str(environment.get(name) or "").strip()
    ]
    if not str(environment.get("YUCE_SESSION_ID") or environment.get("YCSESSIONID") or "").strip():
        missing.append("YUCE_SESSION_ID or YCSESSIONID")
    if missing:
        raise RpaConnectorError(
            "missing RPA runtime environment variables: " + ", ".join(missing)
        )

    api_base = environment["ENV_BACKEND_HOST"].strip().rstrip("/")
    parsed = urlsplit(api_base)
    try:
        valid_port = parsed.port is None or parsed.port > 0
    except ValueError:
        valid_port = False
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or "@" in parsed.netloc
        or parsed.query
        or parsed.fragment
        or not valid_port
    ):
        raise RpaConnectorError(
            "ENV_BACKEND_HOST must be an HTTP(S) gateway URL without credentials, query, or fragment"
        )

    authorization = environment["YUCE_AUTHORIZATION"].strip()
    session_id = str(
        environment.get("YUCE_SESSION_ID")
        or environment.get("YCSESSIONID")
        or authorization
    ).strip()
    cookie_session = str(environment.get("YCSESSIONID") or authorization).strip()
    return api_base, authorization, session_id, {"YCSESSIONID": cookie_session}


def _parse_date(value, field_name):
    if not isinstance(value, str):
        raise RpaConnectorError(
            f"{field_name} must use YYYYMMDD or YYYY-MM-DD format"
        )
    for date_format in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            pass
    raise RpaConnectorError(f"{field_name} must use YYYYMMDD or YYYY-MM-DD format")


def _normalize_multivalue(value, field_name, allowed_values=None):
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                values = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise RpaConnectorError(
                    f"{field_name} must be a comma-separated string or JSON array"
                ) from exc
        else:
            values = value.split(",")
    elif isinstance(value, list):
        values = value
    else:
        raise RpaConnectorError(
            f"{field_name} must be a comma-separated string or JSON array"
        )

    if not isinstance(values, list) or not values:
        raise RpaConnectorError(f"{field_name} must contain one or more strings")
    normalized = []
    for item in values:
        if not isinstance(item, str):
            raise RpaConnectorError(f"{field_name} values must be strings")
        item = item.strip()
        if not item:
            raise RpaConnectorError(f"{field_name} values cannot be blank")
        if item in normalized:
            raise RpaConnectorError(f"{field_name} cannot contain duplicates")
        if allowed_values is not None and item not in allowed_values:
            raise RpaConnectorError(
                f"{field_name} contains an unsupported value: {item}"
            )
        normalized.append(item)
    return normalized


def validate_list_business_params(raw_params):
    if not isinstance(raw_params, dict):
        raise RpaConnectorError("list business_params must be an object")
    unexpected = set(raw_params) - LIST_FIELDS
    if unexpected:
        raise RpaConnectorError(
            "unexpected list business parameters: " + ", ".join(sorted(unexpected))
        )

    params = {}
    if "industry" in raw_params:
        industry = raw_params["industry"]
        if not isinstance(industry, str) or not industry.strip():
            raise RpaConnectorError("industry must be a nonblank string")
        params["industry"] = industry.strip()

    date_range_type = raw_params.get("time_range_type")
    if date_range_type is not None:
        if not isinstance(date_range_type, str) or date_range_type not in DATE_RANGE_TYPES:
            raise RpaConnectorError(
                "time_range_type must be one of: " + ", ".join(sorted(DATE_RANGE_TYPES))
            )
        params["time_range_type"] = date_range_type

    custom_start = raw_params.get("custom_start_date")
    custom_end = raw_params.get("custom_end_date")
    if date_range_type == "CUSTOM":
        if not custom_start or not custom_end:
            raise RpaConnectorError("CUSTOM requires custom_start_date and custom_end_date")
        start = _parse_date(custom_start, "custom_start_date")
        end = _parse_date(custom_end, "custom_end_date")
        today = shanghai_today()
        if start < today - timedelta(days=369):
            raise RpaConnectorError("custom_start_date cannot be more than 369 days before today")
        if end > today - timedelta(days=4):
            raise RpaConnectorError("custom_end_date cannot be later than today-4")
        if end < start:
            raise RpaConnectorError("custom_end_date cannot be earlier than custom_start_date")
        if (end - start).days > 44:
            raise RpaConnectorError("custom date span cannot exceed 44 days")
        params["custom_start_date"] = custom_start
        params["custom_end_date"] = custom_end
    elif custom_start is not None or custom_end is not None:
        raise RpaConnectorError(
            "custom_start_date and custom_end_date are only valid for CUSTOM"
        )

    for field_name in ("ages", "genders", "crowd_groups"):
        if field_name in raw_params:
            params[field_name] = _normalize_multivalue(raw_params[field_name], field_name)

    scope = raw_params.get("brand_scope_type")
    if scope is not None:
        if not isinstance(scope, str) or scope not in BRAND_SCOPE_VALUES:
            raise RpaConnectorError(
                "brand_scope_type must be one of: "
                + ", ".join(sorted(BRAND_SCOPE_VALUES))
            )
        params["brand_scope_type"] = scope
    if "brands" in raw_params:
        brands = _normalize_multivalue(raw_params["brands"], "brands")
        if scope != "SPECIFIED_BRANDS":
            raise RpaConnectorError("brands requires brand_scope_type SPECIFIED_BRANDS")
        if not 3 <= len(brands) <= 10:
            raise RpaConnectorError("brands must contain 3 to 10 values")
        params["brands"] = brands
    elif scope == "SPECIFIED_BRANDS":
        raise RpaConnectorError("SPECIFIED_BRANDS requires brands")

    if "ranking_limit_type" in raw_params:
        ranking_limit_type = raw_params["ranking_limit_type"]
        if (
            not isinstance(ranking_limit_type, str)
            or ranking_limit_type not in RANKING_LIMIT_VALUES
        ):
            raise RpaConnectorError(
                "ranking_limit_type must be one of: "
                + ", ".join(sorted(RANKING_LIMIT_VALUES))
            )
        params["ranking_limit_type"] = ranking_limit_type
    return params


def validate_detail_business_params(raw_params):
    if not isinstance(raw_params, dict):
        raise RpaConnectorError("detail business_params must be an object")
    unexpected = set(raw_params) - DETAIL_FIELDS
    if unexpected:
        raise RpaConnectorError(
            "unexpected detail business parameters: " + ", ".join(sorted(unexpected))
        )
    material_id = raw_params.get("material_id")
    if not isinstance(material_id, str) or not material_id.isdigit():
        raise RpaConnectorError("material_id must contain digits only")
    date_range_type = raw_params.get("date_range_type")
    if date_range_type not in DATE_RANGE_TYPES:
        raise RpaConnectorError(
            "date_range_type must be one of: " + ", ".join(sorted(DATE_RANGE_TYPES))
        )

    params = {"material_id": material_id, "date_range_type": date_range_type}
    start_date = raw_params.get("custom_start_date")
    end_date = raw_params.get("custom_end_date")
    if date_range_type == "CUSTOM":
        if not start_date or not end_date:
            raise RpaConnectorError("CUSTOM requires custom_start_date and custom_end_date")
        start = _parse_date(start_date, "custom_start_date")
        end = _parse_date(end_date, "custom_end_date")
        if end < start:
            raise RpaConnectorError(
                "custom_end_date cannot be earlier than custom_start_date"
            )
        params["custom_start_date"] = start_date
        params["custom_end_date"] = end_date
    elif start_date is not None or end_date is not None:
        raise RpaConnectorError(
            "custom_start_date and custom_end_date are only valid for CUSTOM"
        )
    return params


def _default_session():
    return requests.Session()


def _raise_for_status(response, action):
    try:
        response.raise_for_status()
    except Exception as exc:
        raise RpaConnectorError(f"unable to {action}: {exc}") from exc


def _response_json(response, action):
    try:
        return response.json()
    except Exception as exc:
        raise RpaConnectorError(
            f"unable to decode {action} response as JSON: {exc}"
        ) from exc


def _require_successful_result(result):
    if not isinstance(result, dict) or result.get("success") is not True:
        raise RpaConnectorError("gateway returned an unsuccessful result")
    return result


def list_accounts(environ=None, session=None):
    session = _default_session() if session is None else session
    api_base, authorization, _session_id, cookies = runtime_config(environ)
    try:
        response = session.post(
            f"{api_base}/adg/v1/agent/rpa/authorizations/query",
            json={
                "authorization": authorization,
                "platform": "RPA_JULIANG_YT_ACCOUNT_PASSWORD",
            },
            headers=HEADERS,
            cookies=cookies,
            timeout=30,
        )
    except Exception as exc:
        raise RpaConnectorError(
            "unable to list RPA accounts: transport request failed"
        ) from exc
    _raise_for_status(response, "list RPA accounts")
    return _require_successful_result(_response_json(response, "list RPA accounts"))


def _invoke(operation, shop_id, business_params, environ=None, session=None):
    if operation == "list":
        function_code = "rpa.conn.juliang.yt.industry.content.rankings.list"
    elif operation == "detail":
        function_code = "rpa.conn.juliang.yt.industry.content.rankings.detail"
    else:
        raise RpaConnectorError("operation must be list or detail")
    if not isinstance(shop_id, str) or not shop_id.strip():
        raise RpaConnectorError("shop_id is required")
    session = _default_session() if session is None else session
    api_base, authorization, session_id, cookies = runtime_config(environ)
    try:
        response = session.post(
            f"{api_base}/adg/v1/agent/invoke",
            json={
                "authorization": authorization,
                "agent_session_id": session_id,
                "data_source_type": "rpa",
                "platform": "RPA_JULIANG_YT_ACCOUNT_PASSWORD",
                "function_code": function_code,
                "business_params": business_params,
                "shop_id": shop_id.strip(),
            },
            headers=HEADERS,
            cookies=cookies,
            timeout=RPA_REQUEST_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        raise RpaConnectorError(
            f"unable to fetch RPA {operation}: transport request failed"
        ) from exc
    _raise_for_status(response, f"fetch RPA {operation}")
    return _require_successful_result(
        _response_json(response, f"fetch RPA {operation}")
    )


def invoke_list(shop_id, business_params, environ=None, session=None):
    return _invoke(
        "list",
        shop_id,
        business_params,
        environ=environ,
        session=session,
    )


def invoke_detail(shop_id, business_params, environ=None, session=None):
    return _invoke(
        "detail",
        shop_id,
        business_params,
        environ=environ,
        session=session,
    )


def _batch_invoker():
    return ConnectorInvoker(
        lambda sid, params: invoke_list(sid, params),
        lambda sid, params: invoke_detail(sid, params),
    )


def _positive_int_argument(value):
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list-accounts", help="List available RPA accounts")
    commands.add_parser("schema", help="Print collection parameter metadata")
    commands.add_parser("self-test", help="Run offline connector checks")
    status_parser = commands.add_parser("status", help="Read collection lifecycle state")
    status_parser.add_argument("--output-dir", required=True)
    validate_parser = commands.add_parser("validate", help="Validate and print resolved configuration")
    validate_parser.add_argument("--query-spec", required=True)
    validate_parser.add_argument("--highlight-spec", required=True)
    retry_parser = commands.add_parser(
        "retry-failed", help="Retry rejected detail fetches from an existing batch"
    )
    retry_parser.add_argument("--shop-id", required=True)
    retry_parser.add_argument("--output-dir", required=True)
    retry_unresolved_parser = commands.add_parser(
        "retry-unresolved",
        help="Explicitly retry detail requests interrupted before persistence",
    )
    retry_unresolved_parser.add_argument("--shop-id", required=True)
    retry_unresolved_parser.add_argument("--output-dir", required=True)
    retry_highlights_parser = commands.add_parser(
        "retry-highlights",
        help="Retry missing or unavailable highlighter assets from persisted details",
    )
    retry_highlights_parser.add_argument("--output-dir", required=True)
    facts_parser = commands.add_parser(
        "build-facts", help="Build source-only fact packages from an existing run"
    )
    facts_parser.add_argument("--run-dir", required=True)
    analyze_parser = commands.add_parser(
        "analyze", help="Analyze selected fact packages and render an auditable report"
    )
    analyze_parser.add_argument("--run-dir", required=True)
    analyze_parser.add_argument("--spec", required=True, help="AnalysisSpec JSON path")
    analyze_parser.add_argument("--output", required=True, help="Markdown report output path")
    analyze_parser.add_argument(
        "--analysis-result", help="Optional model-produced AnalysisResult JSON path"
    )
    fetch_parser = commands.add_parser("collect", help="Collect configured rankings, details, and frames")
    fetch_parser.add_argument("--shop-id", required=True)
    fetch_parser.add_argument("--query-spec", required=True)
    fetch_parser.add_argument("--highlight-spec", required=True)
    fetch_parser.add_argument("--output-dir", required=True)
    return parser


def _cmd_self_test():
    if LIST_FUNCTION_CODE != "rpa.conn.juliang.yt.industry.content.rankings.list":
        raise RpaConnectorError("unexpected list function code")
    if DETAIL_FUNCTION_CODE != "rpa.conn.juliang.yt.industry.content.rankings.detail":
        raise RpaConnectorError("unexpected detail function code")
    if PLATFORM != "RPA_JULIANG_YT_ACCOUNT_PASSWORD" or DATA_SOURCE_TYPE != "rpa":
        raise RpaConnectorError("unexpected fixed gateway metadata")
    validate_list_business_params({})
    validate_detail_business_params(
        {"material_id": "1", "date_range_type": "LAST_7_DAYS"}
    )
    print("self-test passed")


def _load_saved_specs(output_dir):
    root = Path(output_dir)
    query = resolve_query_spec(json.loads((root / "resolved-query-spec.json").read_text(encoding="utf-8")))
    highlights = resolve_highlight_spec(json.loads((root / "resolved-highlight-spec.json").read_text(encoding="utf-8")))
    summary = json.loads((root / "run-summary.json").read_text(encoding="utf-8"))
    contract = summary.get("collectionContract") if isinstance(summary, dict) else None
    expected_fingerprint = (
        contract.get("configurationFingerprint") if isinstance(contract, dict) else None
    )
    if expected_fingerprint != spec_fingerprint(query, highlights):
        raise ConfigSpecError(
            "saved configuration fingerprint does not match the collection contract; choose a new output directory"
        )
    return query, highlights


def _build_facts_after_run(output_dir: str | Path) -> dict:
    """Build facts for a changed run and return its manifest."""
    return build_fact_packages(output_dir)


def _print_batch_result(output_dir, facts_manifest):
    print(json.dumps({
        "batch_manifest_path": str(Path(output_dir) / "batch-manifest.json"),
        "facts_manifest_path": str(Path(output_dir) / "facts/manifest.json"),
        "facts_coverage": facts_manifest["coverage"],
    }, ensure_ascii=False, indent=2))


def _draft_analysis_results(spec, selected_facts):
    """Create a conservative offline handoff when no model result file is supplied."""
    results = []
    for section in spec.sections:
        package = selected_facts["sections"].get(section, {})
        records = package.get("records", [])
        result = {"section": section, "findings": [], "gaps": [], "next_questions": []}
        if not records:
            result["gaps"].append("筛选后没有可用事实记录。")
            results.append(result)
            continue
        ref = f"{package['path']}#/records/0"
        if section == "material_ranking":
            result["findings"].append({
                "claim": f"事实包包含 {len(records)} 条榜单记录，首条记录排名为 {records[0].get('rank')}。",
                "type": "fact", "confidence": "high", "fact_refs": [ref],
            })
        elif section == "audience":
            result["findings"].append({
                "claim": f"事实包包含 {len(records)} 条人群记录；标签分布需要基于记录进一步统计。",
                "type": "fact", "confidence": "high", "fact_refs": [ref],
            })
        elif section == "highlight_frames":
            result["findings"].append({
                "claim": f"事实包包含 {len(records)} 个素材的高光帧记录；时间段与指标线索需按素材核验。",
                "type": "fact", "confidence": "high", "fact_refs": [ref],
            })
        elif section == "script":
            result["gaps"].append("脚本字段需检查可用性。")
            for record in records:
                availability = record.get("data_availability", {})
                if any(
                    isinstance(state, dict) and state.get("missing_reason") == "source_empty"
                    for state in availability.values()
                ):
                    result["gaps"] = [
                        "script_text、content_formula、script_segments 为 source_empty，脚本不可分析。"
                    ]
                    break
        results.append(result)
    return results


def _load_analysis_results(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return payload["results"]
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload]
    raise ValueError("analysis result must be an object, result array, or {results: [...]}")


def _analysis_pipeline(run_dir, spec_path, result_path=None):
    root = Path(run_dir)
    spec = parse_analysis_spec(json.loads(Path(spec_path).read_text(encoding="utf-8")))
    selected = load_selected_facts(root, spec)
    fact_index = build_fact_index(selected)
    packet = build_prompt_packet(spec, selected, fact_index)
    results = _load_analysis_results(result_path) if result_path else _draft_analysis_results(spec, selected)
    normalized_results = [normalize_analysis_result(result) for result in results]
    result_errors = [
        error
        for result in normalized_results
        for error in validate_analysis_result(result, fact_index)
    ]
    if result_errors:
        raise ValueError("AnalysisResult 校验失败: " + "; ".join(result_errors))
    manifest = selected["manifest"]
    metadata = {
        "run_id": spec.run_id,
        "analysis_time": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "facts_version": manifest.get("schema_version"),
        "prompt_version": packet["prompt_version"],
        "fact_index": fact_index,
        "coverage": manifest.get("coverage", {}),
        "package_paths": [
            package["path"]
            for package in manifest.get("packages", {}).values()
            if isinstance(package, dict) and isinstance(package.get("path"), str)
        ],
    }
    report = render_analysis_report(spec, normalized_results, metadata)
    result_document = {
        "analysis_id": spec.analysis_id,
        "run_id": spec.run_id,
        "analysis_time": metadata["analysis_time"],
        "facts_version": metadata["facts_version"],
        "prompt_version": metadata["prompt_version"],
        "results": normalized_results,
    }
    return report, result_document, packet


def _write_text_atomically(text, output_path):
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".tmp", dir=target.parent, delete=False) as staging:
        staging_path = Path(staging.name)
        staging.write(text)
    try:
        os.replace(staging_path, target)
    except Exception:
        staging_path.unlink(missing_ok=True)
        raise


def _write_analysis_outputs(output_path, report, result_document, packet):
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    result_output = output.with_suffix(".analysis-result.json")
    prompt_output = output.with_suffix(".prompt-packet.json")
    staging = Path(tempfile.mkdtemp(prefix=".analysis-", dir=output.parent))
    staged_outputs = (
        (staging / output.name, output, "report"),
        (staging / result_output.name, result_output, "result"),
        (staging / prompt_output.name, prompt_output, "prompt"),
    )
    try:
        _write_text_atomically(report, staged_outputs[0][0])
        write_json_atomically(result_document, staged_outputs[1][0])
        write_json_atomically(packet, staged_outputs[2][0])
        # Publish the report last so a failed preparation never leaves a report
        # without its structured result and prompt packet.
        for staged, target, _ in (staged_outputs[1], staged_outputs[2], staged_outputs[0]):
            os.replace(staged, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "list-accounts":
            print(json.dumps(list_accounts(), ensure_ascii=False, indent=2))
            return 0
        if args.command == "schema":
            print(json.dumps(BUSINESS_PARAMS_SCHEMA, ensure_ascii=False, indent=2))
            return 0
        if args.command == "self-test":
            _cmd_self_test()
            return 0
        if args.command == "validate":
            query = resolve_query_spec(json.loads(Path(args.query_spec).read_text(encoding="utf-8")))
            highlights = resolve_highlight_spec(json.loads(Path(args.highlight_spec).read_text(encoding="utf-8")))
            print(json.dumps({"query": query, "highlights": highlights, "fingerprint": spec_fingerprint(query, highlights)}, ensure_ascii=False, indent=2))
            return 0
        if args.command == "status":
            if collection_status is None:
                raise RpaConnectorError("batch status support is unavailable")
            print(json.dumps(collection_status(output_dir=args.output_dir), ensure_ascii=False, indent=2))
            return 0
        if args.command == "retry-failed":
            specs = _load_saved_specs(args.output_dir)
            status = retry_failed_batch(
                shop_id=args.shop_id, output_dir=args.output_dir,
                invoker=_batch_invoker(), highlight_spec=specs[1]
            )
            facts_manifest = _build_facts_after_run(args.output_dir)
            _print_batch_result(args.output_dir, facts_manifest)
            return status
        if args.command == "retry-unresolved":
            specs = _load_saved_specs(args.output_dir)
            status = retry_unresolved_batch(
                shop_id=args.shop_id, output_dir=args.output_dir,
                invoker=_batch_invoker(), highlight_spec=specs[1]
            )
            facts_manifest = _build_facts_after_run(args.output_dir)
            _print_batch_result(args.output_dir, facts_manifest)
            return status
        if args.command == "retry-highlights":
            specs = _load_saved_specs(args.output_dir)
            status = retry_highlights_batch(
                output_dir=args.output_dir, highlight_spec=specs[1]
            )
            facts_manifest = _build_facts_after_run(args.output_dir)
            _print_batch_result(args.output_dir, facts_manifest)
            return status
        if args.command == "build-facts":
            manifest = build_fact_packages(args.run_dir)
            print(json.dumps({
                "manifest_path": str(Path(args.run_dir) / "facts/manifest.json"),
                "coverage": manifest["coverage"],
            }, ensure_ascii=False, indent=2))
            return 0
        if args.command == "analyze":
            report, result_document, packet = _analysis_pipeline(
                args.run_dir, args.spec, args.analysis_result
            )
            _write_analysis_outputs(args.output, report, result_document, packet)
            print(json.dumps({
                "report_path": str(Path(args.output)),
                "analysis_result_path": str(Path(args.output).with_suffix(".analysis-result.json")),
                "prompt_packet_path": str(Path(args.output).with_suffix(".prompt-packet.json")),
            }, ensure_ascii=False, indent=2))
            return 0
        query = resolve_query_spec(json.loads(Path(args.query_spec).read_text(encoding="utf-8")))
        highlights = resolve_highlight_spec(json.loads(Path(args.highlight_spec).read_text(encoding="utf-8")))
        write_resolved_specs(args.output_dir, query, highlights)
        fingerprint = spec_fingerprint(query, highlights)
        status = fetch_batch(
            shop_id=args.shop_id, list_params=query_to_rpa_params(query),
            detail_date_params=detail_to_rpa_params(query),
            target_top_n=query["collection"]["target_top_n"],
            candidate_top_n=query["collection"]["candidate_top_n"],
            output_dir=args.output_dir, invoker=_batch_invoker(),
            highlight_spec=highlights, configuration_fingerprint=fingerprint,
        )
        facts_manifest = _build_facts_after_run(args.output_dir)
        _print_batch_result(args.output_dir, facts_manifest)
        return status
    except (RpaConnectorError, ConfigSpecError, FactPackageError, ValueError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
