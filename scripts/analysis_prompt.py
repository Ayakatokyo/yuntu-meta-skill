"""Build deterministic prompt packets for the current conversation model."""

from __future__ import annotations

from typing import Any

try:
    from .analysis_spec import AnalysisSpec
except ImportError:  # pragma: no cover - direct collector execution
    from analysis_spec import AnalysisSpec


MODULE_REQUIREMENTS = {
    "material_ranking": "分析排名、指标分布、TOP 分层、标签共现、时长与发布时间差异及曝光/点击效率象限；只描述分布或相关线索，不表述因果。",
    "audience": "分析覆盖率、集中度、年龄/性别/人群标签分布，并在多模块时生成素材标签 × 人群标签交叉表；标签不是动机或真实人口统计事实。",
    "script": "检查 script_text、content_formula、script_segments 的可用性；source_empty 时只能报告不可分析和数据缺口，不得用标题或标签代替脚本。",
    "highlight_frames": "按开头、中段、结尾分析高光时间段，联合指标高点/流失点与画面观察；画面只能产生内容观察或待验证线索，不得推导心理或转化原因。",
}


def build_prompt_packet(spec: AnalysisSpec, selected_facts: dict, fact_index: dict[str, object]) -> dict:
    sections = selected_facts.get("sections", {})
    facts = {}
    for section_name in spec.sections:
        section = sections.get(section_name)
        if isinstance(section, dict) and isinstance(section.get("path"), str):
            facts[section["path"]] = section.get("records", [])
    selected_fact_refs = sorted(
        ref
        for ref in fact_index
        if any(ref.startswith(f"{path}#") for path in facts)
    )
    quality_gates = [
        "每条结论必须包含能定位到实际 JSON 记录的 fact_refs；无引用内容只能放入 gaps 或 next_questions。",
        "相关不等于因果；不得使用导致、原因、驱动等因果表述。",
        "品牌归因优先使用原始 brand 字段；selection_group 为空时，标题/标签品牌识别必须标记为推断并降低置信度。",
        "品牌分类只能使用 manifest.brand_classification.candidate_brands；不得使用默认品牌表，也不得根据品类、功效、标签或画面补判品牌。",
        "brand_filter 只能取 manifest 候选品牌或 未知品牌；分析层只消费事实包中的 brand_classification 快照，不重新匹配标题。",
    ]
    script = sections.get("script")
    if script and any(
        "source_empty" in str(record.get("data_availability", {}))
        for record in script.get("records", [])
        if isinstance(record, dict)
    ):
        quality_gates.append("source_empty 只能进入 gaps；脚本模块必须标记不可分析，不得生成脚本事实或替代性结论。")
    brand_classification = selected_facts.get("manifest", {}).get("brand_classification", {})
    return {
        "packet_version": "1",
        "prompt_version": "yuntu-commercial-analysis-v1",
        "analysis_spec": spec.to_dict(),
        "analysis_id": spec.analysis_id,
        "run_id": spec.run_id,
        "business_question": spec.business_question,
        "sections": list(spec.sections),
        "facts": facts,
        "fact_index_refs": selected_fact_refs,
        "module_requirements": {
            section: MODULE_REQUIREMENTS[section] for section in spec.sections
        },
        "brand_classification": brand_classification,
        "rules": {
            "required_fields": ["claim", "type", "confidence", "fact_refs"],
            "allowed_types": ["fact", "inference", "recommendation"],
            "allowed_confidence": ["high", "medium", "low"],
            "quality_gates": quality_gates,
        },
    }
