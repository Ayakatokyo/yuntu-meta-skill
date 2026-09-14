---
name: 云图素材全景诊断
description: 采集巨量云图行业素材及可用源事实，并在第一阶段生成可审计的离线素材榜单报告；第二阶段基于已落盘证据完成商业分析。
metadata:
  argument_hint: 输入行业、时间范围、榜单类型、品牌和人群筛选、素材列表本地筛选及详情素材数。高光帧默认不生成；如选择生成，按下方高光帧设置填写封面、指标、提取规则和帧数。
  pre_input: |
    请采集云图行业素材及相关数据。
    行业是 ____（必填）。
    时间范围是 ____（默认近7天；自定义时填写起止日期）。
    截取方式是 ____（曝光量TOP1000、CTRTOP1000、互动率TOP1000或完播率TOP1000）。
    品牌范围是 ____（默认全行业，或指定3至10个品牌）。
    需要获取详情的素材数是 ____（默认10；详情请求包含秒级拆解和内容公式字段；如同时生成高光帧图片，再按下方规则提取高光帧图片）。
    年龄、性别、八大人群筛选是 ____（可选，留空不过滤）。
    素材列表本地筛选/排序是 ____（可选，例如先落盘完整TOP1000后按“曝光量”>=1000000且“视频标题”包含“燕窝”，再按“互动率”降序）。
    是否同时生成高光帧图片：____（是/否，可选，默认否）。
    高光帧设置（选择否时，以下全部留空；选择是时，按需逐项填写）：
    - 封面是否保留：____（是/否）。
    - 点赞指数：是否选择 ____；提取规则 ____（局部峰值/最高值）；帧数 ____（正整数）。
    - 流失指数：是否选择 ____；提取规则 ____（局部峰值/最高值）；帧数 ____（正整数）。
    - 点击指数：是否选择 ____；提取规则 ____（局部峰值/最高值）；帧数 ____（正整数）。
    - 互动指数：是否选择 ____；提取规则 ____（局部峰值/最高值）；帧数 ____（正整数）。
    - 评论指数：是否选择 ____；提取规则 ____（局部峰值/最高值）；帧数 ____（正整数）。
---

# 可配置云图采集与商业分析工作流

该技能负责榜单、详情、高光帧资产和第一阶段离线报告，并通过同一入口分两阶段运行：阶段一先采集并准备事实资产，确认 `ready_for_analysis` 后调用 `render-overview` 生成可审计的数据工作台报告；报告完成后停止并要求用户直接输入分析思路或商业问题，收到有效问题前不会启动商业分析。用户随后提供分析问题和范围，第二阶段才进入商业分析编排。第一阶段报告只展示已采集事实、确定性统计和已验证本地图片，不生成未经引用的商业洞察。新详情采集固定使用 `rpa.conn.juliang.yt.industry.content.rankings.details`、`date_type` 和异步 fetch task/status；历史批次仍可读取旧详情格式，但不作为新批次回退路径。

## 输入

阶段一生成 `QuerySpec`（行业、周期、筛选、榜单指标、详情素材数），高光帧默认关闭。高光帧配置始终按下方规则理解：选择否时，封面、指标、提取规则和帧数均不填写，系统不生成也不校验图片规则；选择是时，四项设置按要求填写并在取数前校验。请求却缺规则、规则非法，或明确关闭却同时给规则时均在外部取数前报错。采集成功后先落盘源事实和可选图片资产并进入 `ready_for_analysis`，再对同一运行目录执行 `render-overview` 生成第一阶段报告；在报告生成前后均不读取商业问题、不调用分析 Prompt、不生成商业洞察。报告生成成功后才向用户交付阶段一产物并停止。

`QuerySpec` 支持行业、近 7 天、近 30 天或自定义日期、年龄、性别、八大人群、品牌范围、四类榜单指标、详情目标素材数和可选的 `material_list`。周期默认 `LAST_7_DAYS`；自定义日期是闭区间，起止日期均必填并遵循云图可用日期与跨度限制。年龄、性别、八大人群可留空表示不过滤；品牌范围默认为 `ALL_INDUSTRY`，指定品牌时填写 3 至 10 个品牌。详情目标数默认 10，必须为不超过 1000 的正整数。列表候选池由实现固定为 1000，不作为用户输入字段。

`material_list` 只在完整 TOP1000 已落盘并规范化后本地执行，不会进入云图远端 RPA 参数。`filters` 是 AND 条件，`sort` 只能指定一个注册表可排序字段；字段可填写已验证的云图展示名或英文字段 ID。例如：

```json
{
  "material_list": {
    "filters": [
      {"field": "曝光量", "operator": "gte", "value": 1000000},
      {"field": "视频标题", "operator": "contains", "value": "燕窝"}
    ],
    "sort": {"field": "互动率", "direction": "desc"}
  }
}
```

筛选通过后的结果再取前 `target_top_n` 条发起详情采集；完整榜单事实不会被筛选结果覆盖。没有命中时保留完整列表并跳过详情 RPA。该配置不扩展为远端指标筛选、远端排序、商业评分或洞察规则。

### 高光帧规则（可选）

无论“是否同时生成高光帧图片”选择什么，都按以下规则理解：

| 设置 | 选择“否”时 | 选择“是”时 |
| --- | --- | --- |
| 封面设置 | 不填写、不校验 | 必填 `是` 或 `否`，对应 `include_cover` |
| 高光指标 | 不填写、不校验 | 至少选择 1 项，可多选：点赞指数、流失指数、点击指数、互动指数、评论指数 |
| 提取规则 | 不填写、不校验 | 为每个已选指标选择一种：`local_peaks`（局部峰值）或 `top_values`（最高值） |
| 帧数 | 不填写、不校验 | 为每个已选指标填写正整数 `limit`，表示该指标最多提取的帧数，不是所有指标合计帧数 |

选择“否”时只保留视频，不生成高光帧图片；如果同时提交高光规则，会在取数前报错。选择“是”时，配置示例为：

```json
{
  "schema_version": 1,
  "include_cover": true,
  "metrics": {
    "点击指数": {"strategy": "local_peaks", "limit": 3},
    "点赞指数": {"strategy": "top_values", "limit": 2}
  }
}
```

启用图片时，`HighlightSpec` 必须显式包含 `include_cover`（是否保留视频封面），并至少配置以下指标中的一项：点赞指数、流失指数、点击指数、互动指数、评论指数。每个已选指标必须配置一种提取规则：`local_peaks`（局部峰值，优先选择曲线相邻点中形成局部高点的时刻）或 `top_values`（按指标值从高到低选择，值相同优先较早时刻），以及一个正整数 `limit`（该指标最多提取的帧数）。不同指标命中同一秒时合并为一帧；因此实际图片总数可能因合并、可用趋势点不足而少于各指标 `limit` 之和，封面是否计入由 `include_cover` 决定。未请求图片时仅保留视频、不抽帧、不校验 JPEG。第一阶段离线报告在单素材视频预留区以 9:16 播放器展示视频，并只复制经过大小与 SHA-256 校验的视频副本；`trend_series`、`high_points` 和 `loss_points` 仍作为源事实独立可检索。

## 执行

```bash
# 未显式提供配置时，先核对继承环境的目标网关（不发网络请求）
python scripts/collector.py runtime-check
python scripts/collector.py list-accounts
python scripts/collector.py validate --query-spec query.json
python scripts/collector.py collect --shop-id "<shop_id>" --query-spec query.json --output-dir runs/example
# 请求图片时才提供 --highlight-spec；--highlight-mode off 与规则同时出现会被拒绝
python scripts/collector.py collect --shop-id "<shop_id>" --query-spec query.json --highlight-mode on --highlight-spec highlights.json --output-dir runs/example
python scripts/collector.py status --output-dir runs/example
python scripts/collector.py retry-failed --shop-id "<shop_id>" --output-dir runs/example
python scripts/collector.py retry-unresolved --shop-id "<shop_id>" --output-dir runs/example
python scripts/collector.py retry-highlights --output-dir runs/example
python scripts/collector.py build-facts --run-dir runs/example
# 阶段一采集/事实门禁通过后，生成离线第一阶段数据报告；默认写入 runs/example/overview/
python scripts/collector.py render-overview --run-dir runs/example
# 需要显式指定报告目录时，目录必须位于运行目录内
python scripts/collector.py render-overview --run-dir runs/example --output-dir runs/example/overview-preview
# render-overview 成功后停止，等待用户输入商业分析思路或商业问题；收到问题后才进入阶段二
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

### 运行环境与鉴权

用户在当前任务中明确指定的网关和凭证优先于继承环境。提示词中的赋值不会自动改变 shell 环境；必须实际传入采集进程，不能仅检查变量存在就声称已采用用户配置。凭证可来自平台注入或用户主动提供，不能从无关日志、历史产物或配置文件搜集凭证。`CODEX_SESSION_ID` 是 Codex 任务标识，不能作为网关凭证。

用户显式提供配置时，使用 `--runtime-config-stdin`，通过标准输入传入**一行 JSON**：字段仅限 `ENV_BACKEND_HOST`、`YUCE_AUTHORIZATION`、`YUCE_SESSION_ID`、`YCSESSIONID`，值均为字符串；前两个必填，后两个至少一个非空。这是完整配置替换，不与继承凭证混合。只有用户明确说几项值相同时才复用同一个值，不能自行推断。粘贴内容中的 Markdown 链接、转义下划线和 `&#x20;` 是格式，先还原为实际变量名、URL 和值，不能作为凭证字符直接传入。

```bash
# 全局参数放在子命令前；URL 换成用户明确指定的网关，命令中不放凭证
python scripts/collector.py --runtime-config-stdin --expected-gateway https://gateway.example/api list-accounts
python scripts/collector.py --runtime-config-stdin --expected-gateway https://gateway.example/api collect --shop-id "<shop_id>" --query-spec query.json --output-dir runs/example
```

终端交互模式会关闭输入回显，宿主通过终端标准输入发送 JSON 行；管道模式从标准输入读取一行。不要用含真实凭证的 `echo`、heredoc、命令参数或落盘文件构造输入。每次新的 CLI 调用都需要重新传入同一组任务配置（包括 collect、retry-failed、retry-unresolved）；一次调用不会修改全局环境或自动配置后续调用。同一次采集的榜单、详情提交和轮询会共享该配置。

未显式提供配置时保留平台环境兼容路径。`runtime-check` 只显示目标网关、配置来源、变量存在性，不验证认证；RPA 命令也会向 stderr 输出同样的脱敏预检信息，stdout 保持原业务 JSON。用户指定网关时加 `--expected-gateway`，不匹配就会在请求前失败。不要回显凭证或以长度相同判断值相同。

未知 `shop_id` 先查询账号。鉴权失败先看实际网关、配置来源、HTTP 状态、业务 code 与 traceId；已显式提供配置但尚未应用时，先正确传入再重试账号查询。网关 `authentication_failed` 不证明巨量云图网页登录失效；`credential_expired` 表示当前目标网关报告凭证过期。正确配置下仍失败时报告证据与缺少的输入，不能让用户盲目重登云图，也不能反复请求同一套错误配置。保留现有 Cookie 兼容协议：优先使用显式 `YCSESSIONID`，缺省时使用 `YUCE_AUTHORIZATION`。

## 产物与恢复

运行目录包含解析后的配置、`raw-csv/`、`normalized/`、`batch-manifest.json`、`run-summary.json`，以及仅在请求图片时存在的 `highlights-manifest.json` 与 JPEG。详情异步提交会立即在 manifest 的 `taskRuns` 登记 `task_group_id`；恢复只轮询已登记任务，临时网络异常保留为可恢复 unresolved。关闭图片时其状态为 `not_requested`，不是缺包；图片失败不改变已选源素材，但会在第一阶段回执中单独记录。`retry-highlights` 仍是显式第一阶段恢复，第二阶段绝不触发它。

`collect`、`retry-failed`、`retry-unresolved` 和 `retry-highlights` 在更新运行产物后会自动构建 `facts/`，并输出 facts 清单路径、coverage 和 ready 回执；只有采集门禁、四类事实包和品牌分类都完成时才进入 `ready_for_analysis`，阶段一不会自动分析。`status` 会通过 `facts_status` 报告 `complete`、`missing` 或 `invalid`，并返回当前工作流状态。采集完成后也可使用 `build-facts` 将现有运行目录整理为商业分析的事实底座，该命令只读取本地 `normalized/`、`raw-csv/`、`highlights-manifest.json` 和运行摘要，不调用 RPA 或网络，并在 `facts/` 生成素材榜单、人群、脚本、高光帧四类事实包及 `manifest.json`。事实包只做来源字段整理和可用性标记，不生成商业洞察；脚本为空时会保留 `source_empty` 原因。

### 第一阶段报告与停止点

当 `status` 返回 `status=ready_for_analysis` 且 `facts_status=complete` 后，必须对同一 `run_dir` 执行 `render-overview`。该命令只读取已落盘运行数据和注册表，不重新取数、不重新规范化、不重新分类、不启动商业分析；它会校验 `run-summary.json` 中榜单源文件的声明路径、文件大小、SHA-256 和记录数，并将已验证的高光帧/详情图片复制到报告目录。

报告默认生成在 `runs/example/overview/`，核心产物为 `runs/example/overview/overview-data.json` 和 `runs/example/overview/index.html`，必要时附带 `assets/` 下的本地图片。`overview-data.json` 是带来源引用、哈希、可用性和缺口信息的事实投影；`index.html` 是离线数据工作台，展示素材榜单、人群数据、脚本/内容公式、高光帧和已执行详情范围。报告仅展示事实与确定性统计，不得加入 AI 分析、商业结论、行动建议或猜测字段含义。

如果报告生成失败，保留运行目录和失败证据，先修复事实包或源文件校验问题；不得绕过校验进入阶段二。报告生成成功后，阶段一即完成，交付报告路径、事实包路径和数据缺口，并等待用户输入商业分析思路或商业问题。`render-overview` 不会改变 `ready_for_analysis` 状态；只有收到有效分析问题后才进入 `workflow` 或兼容的 `analyze`。

事实包生成时会从本轮 `list_context.brands`（或其 `pre_input.brands`）建立严格的运行时品牌候选范围，不会扩展默认品牌表。标题分类仅对候选品牌执行 Unicode NFKC、`casefold()` 和连续字符串匹配；规范名中的 `/` 表示别名，支持多品牌同时命中，并在 `brand_classification` 中保留 `matchedBrands` 与 `match_tokens` 审计证据。未命中或候选范围缺失时归为 `未知品牌`；`九阳豆浆` 仅支持显式受控的“九阳…豆浆”变体，单独“九阳”不命中。分类不依据品类、功效、标签或画面推断，四类事实包按 `material_id` 传播同一快照。

通过 `.system/skills/custom/yuntu-meta-skill` 执行前，必须运行 `check_runtime_sync.py` 校验运行副本。校验会比较采集器、事实包、第一阶段报告和分析编排模块的 SHA-256，并确认目标 `collector.py --help` 包含 `build-facts` 与 `render-overview`；校验失败时先同步源码脚本再执行。同步只允许写入技能源码和直接依赖，不得复制凭证、`runs/`、`.system/sessions/` 或报告数据。

## 商业分析编排

进入阶段二时必须显式提供 `AnalysisInput`（自然语言问题或结构化 JSON），并选择一个或多个分析模块。`sections` 可选 `material_ranking`、`audience`、`script`、`highlight_frames`；`business_question` 必填。仅选择模块、品牌/素材范围或指标时返回 `analysis_input_required` 并保持 `ready_for_analysis`，不生成任何分析产物。自然语言问题保留原文并标准化；`business_question_source` 为用户问题时记录 `user`，只有用户明确确认系统默认问题时才允许记录 `user_confirmed_default` 且 `user_confirmed: true`。`material_filter.rank_range` 必须位于 1..1000；可选 `brand_filter` 只能取当前 facts manifest 的候选品牌或 `未知品牌`，不允许模型或调用方扩展范围。只有 `ready_for_analysis`（或可验证的历史事实包兼容状态）允许启动分析；未就绪、缺包、未知品牌/素材/指标均返回校验错误。编排器只加载所选事实包，先校验 manifest、包路径、记录数和源文件 SHA-256，再生成带 `fact_refs` 的 PromptPacket。阶段二不重新采集、不重新规范化、不重新分类。

模型结果可通过 `--analysis-result` 传入，作为当前对话模型响应的离线回放/测试入口；未传入时命令只落盘 `*.model-analysis-request.json` 和 `*.prompt-packet.json`，返回 `awaiting_model_analysis` 宿主交接回执，不生成保守分析、结果或报告。宿主协议为 `yuntu-current-conversation-model-v2`：当前对话模型读取 `host_context`，只返回 `AnalysisResult` JSON（对象或 `{\"results\": [...]}`），再用同一运行目录和 `--analysis-result` 恢复。技能脚本不调用外部模型 API，也不启动独立模型。每条 `findings` 结论必须包含可解析的 `fact_refs`、合法的模块、`type` 和 `confidence`。`source_empty` 只能进入 `gaps`；当前脚本字段为空时不得用标题或标签代替脚本。`selection_group.brand_name` 为空且 `brand_classification.source=runtime_title_rule` 时，相关品牌结论必须标记为推断、降低置信度并填写品牌代理说明；标签关联和高光解释不得表述为因果。分析不依赖事后生成的 `fact-summary.json`。

`analyze` 在等待模型时旁写 `<stem>.model-analysis-request.json` 和 `<stem>.prompt-packet.json`；模型结果校验通过后才在 `--output` 写入 Markdown 报告，并旁写 `<stem>.analysis-result.json`。报告正文以核心结论和行动建议开头，随后按 `material_ranking`、`audience`、`script`、`highlight_frames` 固定顺序展示四类事实包；未选择模块明确标注。正文使用 `[E1]` 等短证据编号，不展示 finding 类型、置信度或完整 `fact_refs`；附录 A 保留完整引用索引，附录 B 保留结论类型、置信度、品牌代理说明和逐条审计映射。历史 `AnalysisResult` 缺少展示专用字段时仍按现有 `findings`、`gaps`、`next_questions` 渲染。结果校验失败时只保存包含 `code`、`path`、`message`、`suggestion` 的 `<stem>.analysis-error.json`，保持运行可重试且不生成报告。

新流程优先使用 `workflow`：第一次模型交接只生成 `AnalysisIntent + FactSelectionSpec`，技能在本地从已落盘 `facts/` 选择记录；第二次模型交接只分析 `selected-fact-context.json`。两轮都使用当前会话内模型，阶段二不生成或修改任何 RPA 入参，也不重新采集、规范化或品牌分类。报告额外展示“用户问题 → AnalysisIntent → FactSelectionSpec → 实际选中记录 → 数据缺口 → AI 结论 → fact_refs”链路。不存在的 ROI/GMV 等字段和脚本 `source_empty` 必须显式作为缺口；真实运行中的 1000 条榜单及 306 条未知品牌限制会进入审计。
