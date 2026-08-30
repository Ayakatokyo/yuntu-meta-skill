# 云图商业分析模型二次分析闭环 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将用户分析思路、标准化提示词、事实包和当前对话模型连接为可校验、可落盘、可渲染的二次分析闭环。

**Architecture:** 阶段一在 `ready_for_analysis` 处终止并生成回执；阶段二生成 `ModelAnalysisRequest`，由对话宿主交给当前模型，模型返回 `AnalysisResult` 后由本地校验器和报告渲染器处理。不使用外部模型 API。

**Tech Stack:** Python 3、现有分析编排模块、JSON、Markdown、pytest。

**Spec:** `docs/superpowers/specs/2026-08-30-yuntu-model-analysis-handoff-design.md`

## Global Constraints

- 阶段一不得自动分析或渲染报告。
- 阶段二只读取已落盘事实包，不重新采集、规范化或分类。
- 当前对话模型是唯一 AI 分析执行者，不调用外部模型服务。
- 每条模型结论必须带有效 `fact_refs`。
- 模型失败或结果非法时禁止伪造结果和报告。
- 直接在 `main` 执行，不创建隔离 worktree。

---

## 阶段一：阶段边界与模型请求协议

### Task 1: 固化阶段一停止门禁

**Files:**
- Modify: `scripts/collector.py`
- Modify: `scripts/workflow_state.py`
- Test: `tests/test_two_phase_workflow.py`

**Interfaces:**
- `collect` 成功返回 ready 回执，不创建分析产物。
- `get_workflow_status(run_root: Path) -> dict`

- [ ] 测试阶段一成功时不存在 PromptPacket、AnalysisResult 和报告文件。
- [ ] 测试 partial/failed 运行拒绝进入分析。
- [ ] 实现阶段边界检查并保留历史命令兼容。
- [ ] 运行两阶段状态测试。

### Task 2: 定义 ModelAnalysisRequest

**Files:**
- Modify: `scripts/analysis_prompt.py`
- Create: `scripts/model_analysis_request.py`
- Test: `tests/test_model_analysis_request.py`

**Interfaces:**
- `build_model_analysis_request(spec: AnalysisSpec, selected_facts: dict, fact_index: dict) -> dict`
- `validate_model_analysis_request(request: dict) -> list[str]`

- [ ] 测试请求包含用户问题、分析规格、筛选事实、索引和响应 schema。
- [ ] 测试未选择事实包不出现在请求中。
- [ ] 测试脚本、品牌代理和非因果质量规则被写入请求。
- [ ] 运行请求协议测试。

### 阶段一验收

- [ ] 用真实运行目录确认 collect 后停在 ready，不产生 AI 分析结果。
- [ ] 请求包可被宿主直接转发给当前对话模型。

## 阶段二：当前模型交接与结果落盘

### Task 3: 实现模型交接状态和回执

**Files:**
- Modify: `scripts/workflow_state.py`
- Modify: `scripts/collector.py`
- Test: `tests/test_workflow_state.py`
- Test: `tests/test_collector.py`

**Interfaces:**
- `begin_model_analysis(run_root: Path, request_id: str) -> dict`
- `complete_model_analysis(run_root: Path, result_path: Path) -> dict`

- [ ] 测试 ready → analysis_running → analysis_completed 状态流转。
- [ ] 测试模型失败回到可重试状态且不生成报告。
- [ ] 测试同一运行可再次提交新的 request_id。
- [ ] 运行状态回归测试。

### Task 4: 接入 AnalysisResult 校验和持久化

**Files:**
- Modify: `scripts/analysis_result.py`
- Modify: `scripts/collector.py`
- Test: `tests/test_analysis_result.py`

- [ ] 校验模型返回 JSON、章节、结论类型、置信度和 fact_refs。
- [ ] 拒绝无引用、越界引用、脚本虚构和品牌范围扩展。
- [ ] 保存 request、result、错误信息和版本元数据。
- [ ] 运行结果层完整测试。

### 阶段二验收

- [ ] 使用模拟当前模型响应完成一次结构化结果落盘。
- [ ] 模拟模型失败时不生成报告、不伪造洞察。

## 阶段三：自动编排与端到端验证

### Task 5: 更新技能入口和对话交接说明

**Files:**
- Modify: `SKILL.md`
- Modify: `scripts/collector.py`
- Test: `tests/test_collector.py`

- [ ] 阶段二入口在解析 AnalysisInput 后输出 ModelAnalysisRequest 交接内容。
- [ ] 明确由当前对话模型生成 AnalysisResult，禁止外部 API。
- [ ] 保留 `--analysis-result` 作为离线回放和测试入口。
- [ ] 运行 CLI 相关测试。

### Task 6: 真实目录端到端回归

**Files:**
- Modify: `tests/test_two_phase_workflow.py`
- Create: `tests/fixtures/model-analysis-result-real.json`

- [ ] 阶段一验证 `food-beverage-2026-0810-0820` 停在 ready。
- [ ] 阶段二输入分析思路，生成请求包并用模拟模型响应完成结果和报告。
- [ ] 验证所有 finding 有 fact_refs，脚本缺口和品牌限制存在。
- [ ] 运行完整测试：`pytest -q`。

### 阶段三验收

- [ ] 用户体验为“第一次采集后停止，第二次输入思路后分析并出报告”。
- [ ] 同一运行可重复分析，不重新触发采集。
- [ ] 失败可恢复且不产生不完整报告。

## 完成标准

- [ ] 三阶段测试全部通过。
- [ ] 真实目录端到端验证通过。
- [ ] 文档、CLI、状态机和模型交接协议一致。

