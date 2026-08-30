# 云图元技能两阶段工作流 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将云图元技能拆为采集事实准备阶段和用户驱动商业分析阶段，并保持现有 `pre_input` 兼容。

**Architecture:** 阶段一沿用 `pre_input` 完成采集、分类和事实包，写入可验证的阶段状态；阶段二接收自然语言或结构化 `AnalysisInput`，转换为 `AnalysisSpec`，按需读取事实包并生成分析报告。

**Tech Stack:** Python 3、现有 `scripts/collector.py`、事实包/分析模块、JSON、pytest、Markdown。

**Spec:** `docs/superpowers/specs/2026-08-30-yuntu-two-phase-workflow-design.md`

## Global Constraints

- 现有 `pre_input` 只负责采集筛选条件，不新增商业分析字段。
- 阶段一完成后必须停在 `ready_for_analysis`，不得自动分析。
- 阶段二只能读取已落盘事实包，不重新采集或重新分类。
- 阶段二每条结论必须保留 `fact_refs`。
- 脚本 `source_empty` 只能生成数据缺口。
- 直接在 `main` 执行，不创建隔离 worktree。

---

## 阶段一：采集完成协议与就绪状态

### Task 1: 定义阶段状态和就绪回执

**Files:**
- Create: `scripts/workflow_state.py`
- Test: `tests/test_workflow_state.py`

**Interfaces:**
- `set_stage(run_root: Path, stage: str, **metadata) -> dict`
- `get_workflow_status(run_root: Path) -> dict`
- `build_ready_receipt(run_root: Path) -> dict`

- [ ] 测试合法状态顺序、非法回退和失败状态。
- [ ] 实现状态写入 `run-summary.json`，保留已有运行字段。
- [ ] 实现包含覆盖计数、事实包路径和下一步提示的回执。
- [ ] 运行 `pytest tests/test_workflow_state.py -q`。

### Task 2: 将状态接入采集、事实包和品牌分类门禁

**Files:**
- Modify: `scripts/collector.py`
- Modify: `scripts/fact_packages.py`
- Test: `tests/test_collector.py`
- Test: `tests/test_fact_packages.py`

- [ ] 在采集、规范化、事实包、品牌分类成功节点写入对应阶段。
- [ ] 任一门禁失败时写入 `partial`/`failed`，禁止标记 ready。
- [ ] 事实包和品牌分类完成后自动生成 `ready_for_analysis` 回执。
- [ ] 使用真实运行目录验证阶段状态和覆盖计数。

### 阶段一验收

- [ ] 旧 `pre_input` 无需增加分析字段即可完成阶段一。
- [ ] 阶段一成功后不会调用分析 Prompt 或报告渲染。
- [ ] 用户能从回执获知可用模块、品牌和数据缺口。

## 阶段二：分析输入与事实包选择

### Task 3: 定义 AnalysisInput 解析器

**Files:**
- Create: `scripts/analysis_input.py`
- Test: `tests/test_analysis_input.py`

**Interfaces:**
- `parse_analysis_input(payload: dict | str, run_status: dict, manifest: dict) -> AnalysisSpec`
- `validate_analysis_input(spec: AnalysisSpec, run_status: dict, manifest: dict) -> list[str]`

- [ ] 测试自然语言占位输入、结构化输入、空问题和未知 run_id。
- [ ] 测试非法模块、品牌、排名区间、素材 ID 和指标被拒绝。
- [ ] 实现从阶段二输入到现有 `AnalysisSpec` 的转换。
- [ ] 运行 `pytest tests/test_analysis_input.py -q`。

### Task 4: 接入品牌和素材过滤

**Files:**
- Modify: `scripts/analysis_spec.py`
- Modify: `scripts/analysis_facts.py`
- Test: `tests/test_analysis_spec.py`
- Test: `tests/test_analysis_facts.py`

- [ ] 增加 `brand_filter` 并只允许 manifest 候选或“未知品牌”。
- [ ] 按品牌、排名和素材 ID 组合过滤事实包。
- [ ] 测试同一 `material_id` 在跨模块事实包中的选择一致。
- [ ] 运行分析准备层完整测试。

### 阶段二验收

- [ ] `ready_for_analysis` 运行可创建 AnalysisSpec。
- [ ] 未就绪运行、缺失事实包和无效筛选均不能启动分析。
- [ ] 同一运行目录可创建多个不同 AnalysisSpec，不触发重新采集。

## 阶段三：交互入口与端到端验证

### Task 5: 增加两阶段 CLI/技能入口

**Files:**
- Modify: `scripts/collector.py`
- Modify: `SKILL.md`
- Test: `tests/test_collector.py`

**Interfaces:**
- `collect` 完成后返回 ready 回执。
- `analyze --run-dir <path> --input <path-or-json> --output <path>` 执行阶段二。

- [ ] `analyze` 检查阶段状态并在未 ready 时返回非零状态。
- [ ] 更新技能文档，明确首次调用与后续分析调用的交互示例。
- [ ] 保留旧 `build-facts`、`prepare-analysis` 和历史运行读取兼容。
- [ ] 测试错误路径不会生成不完整报告。

### Task 6: 真实目录纵向验收

**Files:**
- Create: `tests/fixtures/analysis-input-real.json`
- Test: `tests/test_two_phase_workflow.py`

- [ ] 阶段一回执验证 `food-beverage-2026-0810-0820` 的事实包和品牌分类覆盖。
- [ ] 阶段二选择“素材榜单 + 人群 + TOP4 高光帧”并生成结构化结果。
- [ ] 验证脚本缺口、品牌代理限制和 `fact_refs` 均出现在结果中。
- [ ] 运行完整测试：`pytest -q`。

### 阶段三验收

- [ ] 首次调用停在 `ready_for_analysis`，不自动分析。
- [ ] 第二次调用只读取事实包并生成报告。
- [ ] 同一运行目录可重复发起不同分析任务。

## 完成标准

- [ ] 三阶段测试全部通过。
- [ ] 真实运行目录端到端验证通过。
- [ ] `pre_input` 采集协议保持向后兼容。
- [ ] 文档、CLI、状态字段和分析结果契约一致。

