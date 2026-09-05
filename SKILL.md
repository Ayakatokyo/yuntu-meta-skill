---
name: yuntu-meta-skill
description: 通过结构化查询配置采集巨量云图行业内容榜、素材秒级详情和可配置高光帧。适用于需要重复运行、校验口径或生成独立采集技能底座的场景。
argument_hint: 输入行业、时间周期、榜单指标、详情素材数、年龄/性别/八大人群/品牌筛选，以及封面和可选高光指标的截帧策略与帧数；生成并采集 QuerySpec、HighlightSpec 及高光帧资产。
metadata:
  pre_input: 请采集云图行业内容榜单和素材高光帧，行业是 ____（必填）；时间周期是 ____（自定义起止日期，默认近7天）；截取方式是 ____（曝光量TOP1000、CTRTOP1000、互动率TOP1000或完播率TOP1000）；品牌范围是 ____（全行业，或指定3至10个品牌）；需要执行详情拆解的素材数为 ____（正整数，默认10）；年龄是 ____（可选，留空不过滤）；性别是 ____（可选，留空不过滤）；八大人群是 ____（可选，留空不过滤）。高光帧筛选：是否保留封面帧（是/否）；高光指标至少选择一项，可从点赞、流失、点击、互动、评论五项中选择；每个已选指标可按波峰或指标大小截取，并指定帧数。（如：保留封面帧，点赞指数取指标值最高的前 2 帧，流失指数取局部峰值/波峰 2 帧。）
---

# 可配置云图采集与商业分析工作流

该技能负责榜单、详情和高光帧资产，并通过同一入口分两阶段运行：首次调用只采集并准备事实资产，停在 `ready_for_analysis`；阶段一明确停止并要求用户直接输入分析思路或商业问题，收到有效问题前不会启动商业分析。用户随后提供分析问题和范围，第二次调用才进入商业分析编排。采集和事实包阶段不生成未经引用的商业洞察。

## 输入

阶段一的 `pre_input` 只解析现有采集字段，生成 `QuerySpec`（行业、周期、筛选、榜单指标、详情素材数）和 `HighlightSpec`（封面及五项指标的策略/帧数）。成功后立即落盘并返回覆盖回执，停在 `ready_for_analysis`，明确提示“请直接输入分析思路或商业问题；收到前不会启动商业分析”，不读取商业问题、不调用分析 Prompt、不渲染报告。

`QuerySpec` 支持行业、近 7 天、近 30 天或自定义日期、年龄、性别、八大人群、品牌范围、四类榜单指标和详情目标素材数。周期默认 `LAST_7_DAYS`；自定义日期是闭区间，起止日期均必填并遵循云图可用日期与跨度限制。年龄、性别、八大人群可留空表示不过滤；品牌范围默认为 `ALL_INDUSTRY`，指定品牌时填写 3 至 10 个品牌。详情目标数默认 10，必须为不超过 1000 的正整数。列表候选池由实现固定为 1000，不作为用户输入字段。

`HighlightSpec` 必须显式包含 `include_cover`，并至少配置点赞、流失、点击、互动、评论五个指数中的一项；每个已配置维度独立选择 `local_peaks` 或 `top_values` 并指定正整数帧数。`local_peaks` 按局部峰值选帧；`top_values` 按指数值降序、秒点升序选择前 N 个不同秒点，同值时更早秒点优先并占用一个名额。未知字段、策略、空指标集合或非法帧数直接拒绝。

## 执行

```bash
python scripts/collector.py list-accounts
python scripts/collector.py validate --query-spec query.json --highlight-spec highlights.json
python scripts/collector.py collect --shop-id "<shop_id>" --query-spec query.json --highlight-spec highlights.json --output-dir runs/example
python scripts/collector.py status --output-dir runs/example
python scripts/collector.py retry-failed --shop-id "<shop_id>" --output-dir runs/example
python scripts/collector.py retry-unresolved --shop-id "<shop_id>" --output-dir runs/example
python scripts/collector.py retry-highlights --output-dir runs/example
python scripts/collector.py build-facts --run-dir runs/example
# 阶段一返回 ready_for_analysis 后，使用同一个 yuntu-meta-skill 进入两轮阶段二工作流
python scripts/collector.py workflow --run-dir runs/example \
  --business-question "找出曝光高但转化差的素材" --output runs/example/analysis/workflow.md
# 当前对话模型返回 FactSelectionSpec JSON 后回放本地事实选择
python scripts/collector.py workflow --run-dir runs/example \
  --business-question "找出曝光高但转化差的素材" \
  --fact-selection-result runs/example/selection-result.json \
  --output runs/example/analysis/workflow.md
# 当前对话模型返回 AnalysisResult JSON 后生成最终报告
python scripts/collector.py workflow --run-dir runs/example \
  --business-question "找出曝光高但转化差的素材" \
  --analysis-result runs/example/analysis-result.json \
  --output runs/example/analysis/workflow.md
# 历史运行仍可使用旧 AnalysisInput 入口
python scripts/collector.py analyze --run-dir runs/example --input analysis-input.json --output runs/example/analysis.md
# 历史运行仍可使用旧 AnalysisSpec 入口
python scripts/collector.py analyze --run-dir runs/example --spec analysis-spec.json --output runs/example/analysis.md
# analyze 未传 --analysis-result 时只生成宿主交接包，不生成报告；当前对话模型返回 JSON 后回放
python scripts/collector.py analyze --run-dir runs/example --input analysis-input.json \
  --analysis-result runs/example/model-result.json --output runs/example/analysis.md
python scripts/check_runtime_sync.py --target .system/skills/custom/yuntu-meta-skill
```

固定连接器和运行时凭证由平台环境提供；不要把凭证写入命令、配置、清单或输出。未知 `shop_id` 先运行 `list-accounts`。

## 产物与恢复

运行目录包含解析后的配置、`raw-csv/`、`normalized/`、`batch-manifest.json`、`run-summary.json`、`highlights-manifest.json` 和 `highlights/` JPEG 资产。配置、shop ID 或采集参数变化时必须使用新目录。前 N 条中的详情失败会单独落盘，不能用排名更低的素材补位。只有所有目标详情成功且按保存的高光策略生成的帧都可用时，运行才是 `success`；高光帧缺失或不可用时为 `partial`。`retry-failed` 只重试拒绝详情，`retry-unresolved` 只重试未持久化详情，`retry-highlights` 只重建缺失或不可用的高光帧，不重新请求榜单或详情；同一批次的重试会沿用保存的高光策略。

`collect`、`retry-failed`、`retry-unresolved` 和 `retry-highlights` 在更新运行产物后会自动构建 `facts/`，并输出 facts 清单路径、coverage 和 ready 回执；只有采集门禁、四类事实包和品牌分类都完成时才进入 `ready_for_analysis`，阶段一不会自动分析。`status` 会通过 `facts_status` 报告 `complete`、`missing` 或 `invalid`，并返回当前工作流状态。采集完成后也可使用 `build-facts` 将现有运行目录整理为商业分析的事实底座，该命令只读取本地 `normalized/`、`raw-csv/`、`highlights-manifest.json` 和运行摘要，不调用 RPA 或网络，并在 `facts/` 生成素材榜单、人群、脚本、高光帧四类事实包及 `manifest.json`。事实包只做来源字段整理和可用性标记，不生成商业洞察；脚本为空时会保留 `source_empty` 原因。

事实包生成时会从本轮 `list_context.brands`（或其 `pre_input.brands`）建立严格的运行时品牌候选范围，不会扩展默认品牌表。标题分类仅对候选品牌执行 Unicode NFKC、`casefold()` 和连续字符串匹配；规范名中的 `/` 表示别名，支持多品牌同时命中，并在 `brand_classification` 中保留 `matchedBrands` 与 `match_tokens` 审计证据。未命中或候选范围缺失时归为 `未知品牌`；`九阳豆浆` 仅支持显式受控的“九阳…豆浆”变体，单独“九阳”不命中。分类不依据品类、功效、标签或画面推断，四类事实包按 `material_id` 传播同一快照。

通过 `.system/skills/custom/yuntu-meta-skill` 执行前，必须运行 `check_runtime_sync.py` 校验运行副本。校验会比较采集器、事实包和分析编排模块的 SHA-256，并确认目标 `collector.py --help` 包含 `build-facts`；校验失败时先同步源码脚本再执行。同步只允许写入技能源码和直接依赖，不得复制凭证、`runs/`、`.system/sessions/` 或报告数据。

## 商业分析编排

进入阶段二时必须显式提供 `AnalysisInput`（自然语言问题或结构化 JSON），并选择一个或多个分析模块。`sections` 可选 `material_ranking`、`audience`、`script`、`highlight_frames`；`business_question` 必填。仅选择模块、品牌/素材范围或指标时返回 `analysis_input_required` 并保持 `ready_for_analysis`，不生成任何分析产物。自然语言问题保留原文并标准化；`business_question_source` 为用户问题时记录 `user`，只有用户明确确认系统默认问题时才允许记录 `user_confirmed_default` 且 `user_confirmed: true`。`material_filter.rank_range` 必须位于 1..1000；可选 `brand_filter` 只能取当前 facts manifest 的候选品牌或 `未知品牌`，不允许模型或调用方扩展范围。只有 `ready_for_analysis`（或可验证的历史事实包兼容状态）允许启动分析；未就绪、缺包、未知品牌/素材/指标均返回校验错误。编排器只加载所选事实包，先校验 manifest、包路径、记录数和源文件 SHA-256，再生成带 `fact_refs` 的 PromptPacket。阶段二不重新采集、不重新规范化、不重新分类。

模型结果可通过 `--analysis-result` 传入，作为当前对话模型响应的离线回放/测试入口；未传入时命令只落盘 `*.model-analysis-request.json` 和 `*.prompt-packet.json`，返回 `awaiting_model_analysis` 宿主交接回执，不生成保守分析、结果或报告。宿主协议为 `yuntu-current-conversation-model-v2`：当前对话模型读取 `host_context`，只返回 `AnalysisResult` JSON（对象或 `{\"results\": [...]}`），再用同一运行目录和 `--analysis-result` 恢复。技能脚本不调用外部模型 API，也不启动独立模型。每条 `findings` 结论必须包含可解析的 `fact_refs`、合法的模块、`type` 和 `confidence`。`source_empty` 只能进入 `gaps`；当前脚本字段为空时不得用标题或标签代替脚本。`selection_group.brand_name` 为空且 `brand_classification.source=runtime_title_rule` 时，相关品牌结论必须标记为推断、降低置信度并填写品牌代理说明；标签关联和高光解释不得表述为因果。分析不依赖事后生成的 `fact-summary.json`。

`analyze` 在等待模型时旁写 `<stem>.model-analysis-request.json` 和 `<stem>.prompt-packet.json`；模型结果校验通过后才在 `--output` 写入 Markdown 报告，并旁写 `<stem>.analysis-result.json`。报告正文以核心结论和行动建议开头，随后按 `material_ranking`、`audience`、`script`、`highlight_frames` 固定顺序展示四类事实包；未选择模块明确标注。正文使用 `[E1]` 等短证据编号，不展示 finding 类型、置信度或完整 `fact_refs`；附录 A 保留完整引用索引，附录 B 保留结论类型、置信度、品牌代理说明和逐条审计映射。历史 `AnalysisResult` 缺少展示专用字段时仍按现有 `findings`、`gaps`、`next_questions` 渲染。结果校验失败时只保存包含 `code`、`path`、`message`、`suggestion` 的 `<stem>.analysis-error.json`，保持运行可重试且不生成报告。

新流程优先使用 `workflow`：第一次模型交接只生成 `AnalysisIntent + FactSelectionSpec`，技能在本地从已落盘 `facts/` 选择记录；第二次模型交接只分析 `selected-fact-context.json`。两轮都使用当前会话内模型，阶段二不生成或修改任何 RPA 入参，也不重新采集、规范化或品牌分类。报告额外展示“用户问题 → AnalysisIntent → FactSelectionSpec → 实际选中记录 → 数据缺口 → AI 结论 → fact_refs”链路。不存在的 ROI/GMV 等字段和脚本 `source_empty` 必须显式作为缺口；真实运行中的 1000 条榜单及 306 条未知品牌限制会进入审计。
