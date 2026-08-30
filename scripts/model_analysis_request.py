"""Build and validate the request handed to the current conversation model."""

from __future__ import annotations

try:
    from .analysis_prompt import build_prompt_packet
    from .analysis_spec import AnalysisSpec
except ImportError:  # pragma: no cover - direct script imports
    from analysis_prompt import build_prompt_packet
    from analysis_spec import AnalysisSpec


REQUEST_TYPE = "yuntu_commercial_analysis"
REQUEST_VERSION = 1
RESPONSE_SCHEMA = "AnalysisResult"

BASE_SYSTEM_RULES = (
    "只使用给定事实，不补充外部资料或未提供的记录。",
    "每条结论必须带能定位到事实记录的 fact_refs。",
    "相关不等于因果；不得把相关、共现或高光解释表述为因果。",
    "品牌代理识别必须标记为推断并降低置信度，且只能使用运行时品牌候选范围。",
    "脚本字段为 source_empty 时只能进入 gaps，不得用标题或标签替代脚本。",
)


def build_model_analysis_request(
    spec: AnalysisSpec,
    selected_facts: dict,
    fact_index: dict[str, object],
) -> dict:
    """Create a host-ready, JSON-serializable model handoff request."""
    if not isinstance(spec, AnalysisSpec):
        raise ValueError("spec must be an AnalysisSpec")
    packet = build_prompt_packet(spec, selected_facts, fact_index)
    rules = list(BASE_SYSTEM_RULES)
    for rule in packet.get("rules", {}).get("quality_gates", []):
        if rule not in rules:
            rules.append(rule)
    selected_paths = set(packet.get("facts", {}))
    selected_index = {
        ref: record
        for ref, record in fact_index.items()
        if any(ref.startswith(f"{path}#") for path in selected_paths)
    }
    return {
        "request_type": REQUEST_TYPE,
        "request_version": REQUEST_VERSION,
        "analysis_id": spec.analysis_id,
        "run_id": spec.run_id,
        "system_rules": rules,
        "analysis_spec": spec.to_dict(),
        "facts": packet.get("facts", {}),
        "fact_index": selected_index,
        "response_schema": RESPONSE_SCHEMA,
    }


def validate_model_analysis_request(request: dict) -> list[str]:
    """Return protocol errors without making network or model calls."""
    errors: list[str] = []
    if not isinstance(request, dict):
        return ["request must be an object"]
    if request.get("request_type") != REQUEST_TYPE:
        errors.append(f"request_type must be {REQUEST_TYPE}")
    version = request.get("request_version")
    if isinstance(version, bool) or version != REQUEST_VERSION:
        errors.append(f"request_version must be {REQUEST_VERSION}")
    for field in ("analysis_id", "run_id"):
        value = request.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{field} is required")
    rules = request.get("system_rules")
    if not isinstance(rules, list) or not rules or any(
        not isinstance(rule, str) or not rule.strip() for rule in rules
    ):
        errors.append("system_rules must be a non-empty string array")
    if not isinstance(request.get("analysis_spec"), dict):
        errors.append("analysis_spec must be an object")
    facts = request.get("facts")
    if not isinstance(facts, dict):
        errors.append("facts must be an object")
    fact_index = request.get("fact_index")
    if not isinstance(fact_index, dict):
        errors.append("fact_index must be an object")
    if isinstance(facts, dict) and isinstance(fact_index, dict):
        fact_paths = set(facts)
        for path, records in facts.items():
            if not isinstance(path, str) or not isinstance(records, list):
                errors.append("facts must map package paths to record arrays")
        for ref in fact_index:
            if not isinstance(ref, str) or "#" not in ref:
                errors.append("fact_index keys must be fact references")
                continue
            if ref.split("#", 1)[0] not in fact_paths:
                errors.append(f"fact_index reference is outside selected facts: {ref}")
    if request.get("response_schema") != RESPONSE_SCHEMA:
        errors.append(f"response_schema must be {RESPONSE_SCHEMA}")
    return errors


__all__ = [
    "REQUEST_TYPE",
    "REQUEST_VERSION",
    "RESPONSE_SCHEMA",
    "build_model_analysis_request",
    "validate_model_analysis_request",
]
