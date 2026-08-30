"""Validation and normalization for model-produced commercial analysis results."""

from __future__ import annotations

from copy import deepcopy
from typing import Any


ALLOWED_TYPES = {"fact", "inference", "recommendation"}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}
ALLOWED_SECTIONS = {"material_ranking", "audience", "script", "highlight_frames"}
CAUSAL_MARKERS = ("导致", "因为", "原因是", "驱动", "造成", "促成", "带来", "说明了")
BRAND_PROXY_MARKERS = ("标题识别品牌", "标签识别品牌", "品牌识别", "品牌归因", "推断品牌")


def normalize_analysis_result(result: dict) -> dict:
    if not isinstance(result, dict):
        raise ValueError("analysis result must be an object")
    normalized = deepcopy(result)
    normalized.setdefault("findings", [])
    normalized.setdefault("gaps", [])
    normalized.setdefault("next_questions", [])
    return normalized


def _has_source_empty(value: Any, *, ignore_script_fields: bool = False) -> bool:
    if isinstance(value, dict):
        availability = value.get("data_availability")
        if isinstance(availability, dict):
            if (
                availability.get("available") is False
                and availability.get("missing_reason") == "source_empty"
            ):
                return True
            for field_name, state in availability.items():
                if ignore_script_fields and field_name in {
                    "script_text", "content_formula", "script_segments", "selection_group"
                }:
                    continue
                if isinstance(state, dict) and (
                    state.get("missing_reason") == "source_empty"
                    or state.get("available") is False and state.get("missing_reason") == "source_empty"
                ):
                    return True
        return any(
            _has_source_empty(item, ignore_script_fields=ignore_script_fields)
            for key, item in value.items()
            if key != "data_availability"
        )
    if isinstance(value, list):
        return any(
            _has_source_empty(item, ignore_script_fields=ignore_script_fields)
            for item in value
        )
    return False


def _is_brand_proxy(claim: str) -> bool:
    return any(marker in claim for marker in BRAND_PROXY_MARKERS)


def _record_has_empty_brand(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    selection = record.get("selection_group")
    if isinstance(selection, dict) and not str(selection.get("brand_name") or "").strip():
        return True
    availability = record.get("data_availability")
    state = availability.get("selection_group") if isinstance(availability, dict) else None
    return isinstance(state, dict) and state.get("available") is False


def validate_analysis_result(
    result: dict, fact_index: dict, allowed_sections: set[str] | None = None
) -> list[str]:
    """Return gate failures; a non-empty list must prevent report rendering."""
    errors: list[str] = []
    try:
        normalized = normalize_analysis_result(result)
    except ValueError as exc:
        return [str(exc)]
    section = normalized.get("section")
    if not isinstance(section, str) or not section.strip():
        errors.append("section is required")
    elif section not in (allowed_sections or ALLOWED_SECTIONS):
        errors.append(f"section is not an allowed analysis module: {section}")
    findings = normalized.get("findings")
    if not isinstance(findings, list):
        return errors + ["findings must be an array"]
    if not isinstance(fact_index, dict):
        return errors + ["fact_index must be an object"]
    for position, finding in enumerate(findings):
        prefix = f"findings[{position}]"
        if not isinstance(finding, dict):
            errors.append(f"{prefix} must be an object")
            continue
        claim = finding.get("claim")
        if not isinstance(claim, str) or not claim.strip():
            errors.append(f"{prefix}.claim is required")
        finding_type = finding.get("type")
        if finding_type not in ALLOWED_TYPES:
            errors.append(f"{prefix}.type must be one of: {', '.join(sorted(ALLOWED_TYPES))}")
        confidence = finding.get("confidence")
        if confidence not in ALLOWED_CONFIDENCE:
            errors.append(f"{prefix}.confidence must be one of: {', '.join(sorted(ALLOWED_CONFIDENCE))}")
        refs = finding.get("fact_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"{prefix}.fact_refs must contain at least one reference")
            continue
        if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
            errors.append(f"{prefix}.fact_refs must contain strings")
            continue
        referenced_records = []
        for ref in refs:
            if ref not in fact_index:
                errors.append(f"{prefix}.fact_ref does not resolve: {ref}")
            else:
                referenced_records.append(fact_index[ref])
        if any(
            _has_source_empty(
                fact_index[ref],
                ignore_script_fields="highlight-frames.json" in ref,
            )
            for ref in refs
            if ref in fact_index
        ):
            errors.append(f"{prefix} references source_empty data; source_empty may only enter gaps")
        claim_text = claim if isinstance(claim, str) else ""
        if any(marker in claim_text for marker in CAUSAL_MARKERS):
            errors.append(f"{prefix} 包含不受支持的因果表述；相关不等于因果")
        if any(marker in claim_text for marker in ("关联", "相关", "共现", "交叉")) and finding_type != "inference":
            errors.append(f"{prefix} 标签关联必须标记为 inference")
        is_empty_brand = any(_record_has_empty_brand(record) for record in referenced_records)
        mentions_brand_candidate = any(
            isinstance(record, dict)
            and isinstance(record.get("list_context"), dict)
            and any(
                isinstance(candidate, str) and candidate.strip() and candidate in claim_text
                for candidate in record["list_context"].get("brands", [])
            )
            for record in referenced_records
        )
        if _is_brand_proxy(claim_text) or (is_empty_brand and mentions_brand_candidate):
            if finding_type != "inference":
                errors.append(f"{prefix} 品牌代理识别必须标记为 inference")
            if confidence == "high":
                errors.append(f"{prefix} 品牌代理识别不能使用 high confidence")
        if section == "highlight_frames" and any(
            marker in claim_text for marker in ("高光", "画面", "节奏", "流失")
        ) and finding_type != "inference" and not any(
            marker in claim_text for marker in ("事实", "记录", "第", "秒")
        ):
            errors.append(f"{prefix} 高光解释必须标记为 inference")
    for field_name in ("gaps", "next_questions"):
        if not isinstance(normalized.get(field_name), list):
            errors.append(f"{field_name} must be an array")
    return errors
