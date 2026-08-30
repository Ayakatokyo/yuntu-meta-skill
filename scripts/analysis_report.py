"""Render the fixed, auditable Markdown report for validated analysis results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

try:
    from .analysis_result import normalize_analysis_result, validate_analysis_result
    from .analysis_spec import AnalysisSpec
except ImportError:  # pragma: no cover - direct collector execution
    from analysis_result import normalize_analysis_result, validate_analysis_result
    from analysis_spec import AnalysisSpec


FIXED_SECTIONS = (
    ("material_ranking", "素材榜单表现"),
    ("audience", "人群结构"),
    ("script", "脚本可用性与数据缺口"),
    ("highlight_frames", "高光帧与内容节奏"),
)


def _text(value: Any) -> str:
    if isinstance(value, dict):
        if "claim" in value:
            return str(value["claim"])
        return "; ".join(f"{key}: {val}" for key, val in value.items())
    return str(value)


def _render_findings(results: list[dict]) -> list[str]:
    lines: list[str] = []
    for result in results:
        for finding in result.get("findings", []):
            refs = ", ".join(finding["fact_refs"])
            lines.append(
                f"- [{finding['type']}/{finding['confidence']}] {finding['claim']} "
                f"（fact_refs: `{refs}`）"
            )
        for gap in result.get("gaps", []):
            lines.append(f"- 数据缺口：{_text(gap)}")
        for question in result.get("next_questions", []):
            lines.append(f"- 待验证问题：{_text(question)}")
    return lines or ["- 本次没有已校验结论或数据缺口。"]


def render_analysis_report(spec: AnalysisSpec, results: list[dict], metadata: dict) -> str:
    if not isinstance(spec, AnalysisSpec):
        raise ValueError("spec must be an AnalysisSpec")
    if not isinstance(results, list):
        raise ValueError("results must be an array")
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    required_metadata = ("run_id", "analysis_time", "facts_version", "prompt_version", "fact_index")
    missing = [name for name in required_metadata if name not in metadata]
    if missing:
        raise ValueError("报告元数据缺失: " + ", ".join(missing))
    fact_index = metadata["fact_index"]
    errors: list[str] = []
    normalized_results: list[dict] = []
    for result in results:
        normalized = normalize_analysis_result(result)
        errors.extend(validate_analysis_result(normalized, fact_index))
        normalized_results.append(normalized)
    if errors:
        raise ValueError("校验失败，禁止渲染报告: " + "; ".join(errors))

    selected = set(spec.sections)
    custom_names = [item if isinstance(item, str) else item["name"] for item in spec.custom_sections]
    custom_names = [name for name in custom_names if isinstance(name, str) and name.strip()]
    allowed = selected | set(custom_names)
    unknown = sorted({result["section"] for result in normalized_results if result.get("section") not in allowed})
    if unknown:
        raise ValueError("报告包含未选择的结果章节: " + ", ".join(unknown))
    grouped: dict[str, list[dict]] = {}
    for result in normalized_results:
        section = result["section"]
        if section in allowed:
            grouped.setdefault(section, []).append(result)
    missing_sections = sorted(selected - set(grouped))
    if missing_sections:
        raise ValueError("报告缺少所选章节的结果或数据缺口: " + ", ".join(missing_sections))

    generated_at = metadata.get("analysis_time") or datetime.now(timezone.utc).isoformat()
    coverage = metadata.get("coverage", {})
    package_paths = metadata.get("package_paths", [])
    if not package_paths:
        package_paths = sorted({ref.split("#/", 1)[0] for ref in fact_index})
    lines = [
        "# 云图商业分析报告",
        "",
        "## 执行摘要",
        "",
    ]
    summary_results = [grouped[name] for name in spec.sections if name in grouped]
    summary = [finding for group in summary_results for result in group for finding in result.get("findings", [])]
    if summary:
        lines.extend(_render_findings([{"findings": summary, "gaps": [], "next_questions": []}]))
    else:
        lines.append("- 本次没有可进入执行摘要的已校验结论。")
    lines.extend([
        "",
        "## 分析范围、样本和方法",
        "",
        f"- analysis_id：`{spec.analysis_id}`",
        f"- run_id：`{metadata['run_id']}`",
        f"- 分析时间：`{generated_at}`",
        f"- 事实包版本：`{metadata['facts_version']}`；提示词版本：`{metadata['prompt_version']}`",
        f"- 选择模块：{', '.join(spec.sections)}；商业问题：{spec.business_question}",
        f"- 样本覆盖：`{coverage}`",
        "- 事实包路径：" + ", ".join(f"`{path}`" for path in package_paths),
        "- 方法：仅向当前对话模型提供已选择、已校验的事实包，并要求每条结论回填 `fact_refs`。",
        "",
    ])
    for section, heading in FIXED_SECTIONS:
        lines.extend([f"## {heading}", ""])
        if section in selected:
            lines.extend(_render_findings(grouped.get(section, [])))
        else:
            lines.append("- 本次未选择该模块。")
        lines.append("")
    for custom_name in custom_names:
        lines.extend([f"## {custom_name}", ""])
        lines.extend(_render_findings(grouped.get(custom_name, [])))
        lines.append("")
    lines.extend([
        "## 跨模块观察",
        "",
        "- 只有在同时选择多个模块时才解释跨模块线索；标签共现和指标关联仅表示观察，相关不等于因果。",
        "",
        "## 商业机会与待验证假设",
        "",
        "- 任何机会均需由带 `fact_refs` 的推断或建议支撑，并在下一轮实验中验证。",
        "",
        "## 执行动作建议",
        "",
        "- 优先补充可回溯的脚本字段，并针对高光时间段与指标线索设计对照实验。",
        "",
        "## 数据限制与下一轮采集建议",
        "",
        "- `source_empty` 字段只能作为数据缺口；当前脚本不可分析，不得用标题或标签替代脚本。",
        "- 当前 `selection_group` 品牌字段为空；标题/标签品牌识别只能作为品牌代理识别推断，并降低置信度。",
        "- 相关线索不等于因果关系；高光画面不得直接推导用户心理或转化原因。",
        "",
        "## 事实引用附录",
        "",
    ])
    appendix_seen = set()
    for result in normalized_results:
        if result["section"] not in allowed:
            continue
        for finding in result.get("findings", []):
            for ref in finding["fact_refs"]:
                key = (ref, finding["claim"])
                if key in appendix_seen:
                    continue
                appendix_seen.add(key)
                lines.append(f"- `{ref}`：{finding['claim']}")
    if not appendix_seen:
        lines.append("- 本次没有事实结论引用。")
    return "\n".join(lines).rstrip() + "\n"
