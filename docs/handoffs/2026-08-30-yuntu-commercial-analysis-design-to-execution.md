# 云图元技能商业分析交接摘要

## 交接说明

本对话主要负责需求澄清、架构设计、设计文档和执行计划；实际代码执行均通过新开 Codex 任务完成，主要使用 GPT-5.6 Luna 高推理强度，直接在 `main` 分支且不创建隔离 worktree。

## 已完成的设计与执行

### 事实包与品牌分类

- 四类事实包：素材榜单、人群、脚本、高光帧。
- 品牌分类严格使用本轮指定品牌，支持 `/` 拆分、Unicode/大小写归一化、多品牌命中、未知品牌和受控变体。
- 分类保留 `matchedBrands` 与命中 token，供审计和后续分析。

### 商业分析编排

- `AnalysisSpec`：模块、品牌、排名/素材范围、指标和商业问题。
- 事实包选择与 manifest/SHA-256 校验。
- `PromptPacket`：只携带用户选择的事实和 `fact_refs`。
- `AnalysisResult`：强制结论类型、置信度、引用和数据缺口。
- 固定 Markdown 报告骨架、品牌审计、事实引用附录和自定义章节。

### 两阶段工作流

```text
阶段一：pre_input → 采集/规范化/事实包/品牌分类 → ready_for_analysis → 停止
阶段二：分析思路 → AnalysisSpec → PromptPacket → 当前对话模型 → AnalysisResult → 报告
```

阶段一不自动分析；同一运行目录可多次发起阶段二分析，不重新采集或分类。

### 当前模型二次分析闭环

已实现宿主交接协议 `yuntu-current-conversation-model-v2`：技能生成分层的 `ModelAnalysisRequest`，宿主读取 `host_context`，本地审计信息放在 `local_audit`；请求保留事实引用、事实包版本、哈希、分析 ID 和可追溯性，不重复携带完整 `fact_index`，也不依赖事后临时生成的 `fact-summary.json`。当前对话模型返回 `AnalysisResult` JSON 后，技能随后校验、落盘并渲染报告。技能不调用外部模型 API。无模型响应时只保存交接请求，不伪造商业洞察。

## 关键执行任务

- 商业分析/品牌分类：`01a050c8-bc48-7c81-9b99-35aa90b6ca5a`
- 两阶段工作流：`01a05120-48ec-7083-a832-a9b123c99428`
- 模型二次分析闭环：`01a0518d-ca6a-7971-83ef-4c2dfcfed1af`
- 高光帧深秒点修复：`01a05160-26c2-7f03-ad22-b7a50f829318`

## 关键提交

- `8fc4050`：事实包品牌分类设计
- `f66e198`：素材分析品牌识别
- `5f82656`：素材采集后的商业分析能力
- `a0094b8`：两阶段采集分析流程
- `23c4990`：高光帧提取与失败提示优化
- `9561713`：模型二次分析交接设计

## 验证情况

在 `runs/food-beverage-2026-0810-0820` 上完成两阶段端到端验证。最近一次模型交接任务报告：`pytest -q` 为 169 passed、11 subtests passed，编译检查和 `git diff --check` 通过。

高光帧深秒点问题的根因是下载超时与 ffmpeg 解码超时复用 30 秒预算；后续已开启独立修复任务，需在继续工作前确认其最终提交和真实 31s/47s 回归结果。

## 后续 Terra 对话入口

后续如使用 GPT-5.6 Terra 进行方案设计，应先读取：

1. `SKILL.md`
2. `docs/superpowers/specs/2026-08-30-yuntu-two-phase-workflow-design.md`
3. `docs/superpowers/specs/2026-08-30-yuntu-model-analysis-handoff-design.md`
4. `docs/superpowers/plans/2026-08-30-yuntu-two-phase-workflow.md`
5. `docs/superpowers/plans/2026-08-30-yuntu-model-analysis-handoff.md`
6. 本交接摘要

Terra 设计阶段应将本摘要视为现状基线，先确认当前工作树和未提交改动，再提出新的设计方案；不要重复实现已完成的两阶段、事实包或模型交接能力。
