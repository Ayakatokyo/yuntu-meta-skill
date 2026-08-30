# 云图商业分析模型二次分析闭环设计

## 1. 目标

在现有两阶段工作流上补齐模型闭环：阶段一使用 `pre_input` 完成采集与事实准备后必须停止；阶段二接收用户分析思路，将其标准化为提示词并连同对应事实包交给当前对话模型，接收结构化 `AnalysisResult` 后再落盘和渲染报告。

## 2. 核心边界

Python 技能脚本不调用外部模型 API，也不启动独立模型。技能负责生成可执行的 `ModelAnalysisRequest`；当前对话宿主负责把该请求交给本轮模型继续生成结果。模型结果返回后由技能校验、保存和渲染。

## 3. 两阶段交互

### 阶段一

`pre_input → collect → normalize → fact packages → brand classification → ready_for_analysis`

进入 `ready_for_analysis` 后只返回覆盖回执、可用事实包、品牌范围和数据缺口，并输出下一步提示。阶段一不得读取商业问题、生成 PromptPacket、请求模型分析或渲染报告。

### 阶段二

`AnalysisInput → AnalysisSpec → selected facts → ModelAnalysisRequest → current conversation model → AnalysisResult → report`

阶段二必须引用已处于 `ready_for_analysis` 的运行目录；同一运行可重复发起多个分析请求，不重新采集、规范化或品牌分类。

## 4. ModelAnalysisRequest 契约

```json
{
  "request_type": "yuntu_commercial_analysis",
  "request_version": 2,
  "host_context": {
    "analysis_id": "uuid",
    "run_id": "...",
    "analysis_spec": {},
    "facts": {},
    "fact_refs": ["facts/material-ranking.json#/records/0"],
    "system_rules": ["只使用给定事实", "每条结论必须带 fact_refs"],
    "response_schema": "AnalysisResult"
  },
  "local_audit": {
    "analysis_id": "uuid",
    "run_id": "...",
    "facts_version": 3,
    "prompt_version": "yuntu-commercial-analysis-v1",
    "fact_package_hashes": {},
    "source_artifact_hashes": {},
    "selected_fact_paths": ["facts/material-ranking.json"]
  }
}
```

`host_context` 是宿主交接所需的最小上下文：`facts` 只包含用户选择的模块和筛选后的记录，`fact_refs` 提供可引用路径；不再重复携带本地完整 `fact_index`。`local_audit` 仅供技能落盘和审计，保留分析 ID、运行 ID、事实包版本、提示词版本、事实包/源文件哈希和选中路径。请求不得依赖事后临时生成的 `fact-summary.json`，并必须明确脚本 `source_empty`、品牌代理识别和相关不等于因果等约束。

## 5. 模型交接与结果

当前对话模型读取 `ModelAnalysisRequest` 后返回 `AnalysisResult` JSON。技能验证模块、结论类型、置信度和 `fact_refs`，验证失败则停止，不渲染报告，并返回可修正的错误。验证通过后保存请求、结果和报告元数据。

若当前宿主无法完成模型交接，系统只能保存待分析请求并提示用户继续，不得伪造模型结果；保守事实摘要仍标记为非 AI 洞察。

## 6. 报告输出

报告渲染只消费已验证的 `AnalysisResult`，不新增判断。输出：Markdown 报告、结构化结果、模型请求包和分析状态。报告必须包含分析范围、事实包版本、模型请求版本、数据缺口和事实引用附录。

## 7. 验收标准

- 阶段一真实运行后停在 `ready_for_analysis`，没有分析产物。
- 阶段二生成一个包含分析思路和事实包的 `ModelAnalysisRequest`。
- 当前对话模型返回结果后，所有结论均通过 `fact_refs` 校验并落盘。
- 模型失败或结果非法时不生成报告。
- 同一运行可重复分析，且不重新采集或分类。
