---
name: 云图行业素材数据工作台
description: 围绕行业、品牌、人群与内容表现采集巨量云图素材及诊断事实，形成可审计的数据资产和素材数据工作台，供后续自定义内容分析与经营使用。
argument_hint: 输入行业、时间范围、榜单类型、品牌和人群筛选、素材列表本地筛选及详情素材数。高光帧默认不生成；如选择生成，直接输入包含封面、指标、提取规则和帧数的自然语言规则。
compatibility:
  - data-analysis
  - python
  - html-report
---

# 云图行业素材数据工作台

该技能负责榜单、详情、高光帧资产和第一阶段离线报告，并通过同一入口分两阶段运行：阶段一先采集并准备事实资产，确认 `ready_for_analysis` 后调用 `render-overview` 生成可审计的数据工作台报告；报告完成后停止并要求用户直接输入分析思路或商业问题，收到有效问题前不会启动商业分析。用户随后提供分析问题和范围，第二阶段才进入商业分析编排。第一阶段报告只展示已采集事实、确定性统计和已验证本地图片，不生成未经引用的商业洞察。列表与新详情分别只静态保存 connector code，平台、输入契约和输出字段全部在运行时读取；历史批次仍可读取旧详情格式，但不作为新批次回退路径。

同一运行目录可以并行承载多个第二阶段问题。采集与事实就绪状态仍保留在运行目录根部；每次 `workflow` 启动会返回唯一的 `analysis_id`，并把该问题的输入、事实选择、模型交接、状态和报告写入 `analysis/<analysis_id>/`。后续回放必须携带该 `analysis_id`；不同 ID 互不覆盖，也不会把运行目录从 `ready_for_analysis` 置为分析中状态。

## 输入

云图没有独立的 API 报表店铺阶段。先选择 `rpa_shop`：榜单和素材详情均通过 `RPA_JULIANG_YT_ACCOUNT_PASSWORD` 获取，`rpa_shop.extra.shop_id` 是这两个步骤唯一使用的授权账号 ID，必须原样同时传入两步的 `--shop-id`；不得再手填、猜测或替换账号。执行每个阶段前查询当前授权列表：所选账号不在列表时以 `rpa_shop_not_authorized` 停止，不提交后续 RPA 任务，也不改用其他账号。

阶段一生成 `QuerySpec`（行业、周期、筛选、榜单指标、详情素材数），高光帧默认关闭。高光帧配置始终按下方规则理解：选择否时，封面、指标、提取规则和帧数均不填写，系统不生成也不校验图片规则；选择是时，四项设置按要求填写并在取数前校验。请求却缺规则、规则非法，或明确关闭却同时给规则时均在外部取数前报错。采集成功后先落盘源事实和可选图片资产并进入 `ready_for_analysis`，再对同一运行目录执行 `render-overview` 生成第一阶段报告；在报告生成前后均不读取商业问题、不调用分析 Prompt、不生成商业洞察。报告生成成功后才向用户交付阶段一产物并停止。

`QuerySpec` 支持行业、近 7 天、近 30 天或自定义日期、年龄、性别、八大人群、品牌范围、四类榜单指标、详情目标素材数和可选的 `material_list`。周期默认 `LAST_7_DAYS`；自定义日期是闭区间，起止日期均必填，按北京时间计算结束日期最晚为执行日前 4 天（T+4），开始日期不早于执行日前 369 天，跨度为 1 至 45 天。自定义日报的缺省统计日可提议前 4 天；用户明确指定较晚日期时必须在外部取数前拒绝，不得静默改日期。`LAST_7_DAYS` 和 `LAST_30_DAYS` 仍按连接器的周期语义提交，不伪装成自定义日期。年龄、性别、八大人群可留空表示不过滤；品牌范围默认为 `ALL_INDUSTRY`，指定品牌时填写 3 至 10 个品牌。多选筛选在输入阶段可用列表、英文逗号分隔字符串或 JSON 数组字符串；提交实时连接器时统一编码为英文逗号分隔的 STRING，枚举值逐项校验。详情目标数默认 10，必须为不超过 1000 的正整数。列表候选池由实现固定为 1000，不作为用户输入字段。

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

执行前保持当前目录为用户工作对象目录，并先保存 `WORKSPACE_ROOT="$PWD"`；技能脚本通过技能安装目录的绝对路径读取，运行产物一律显式写入 `$WORKSPACE_ROOT`。不得 `cd` 到技能目录后创建运行目录，也不得把技能目录赋给 `WORKSPACE_ROOT`。

```bash
# SKILL_ROOT 由宿主解析为当前技能安装目录；PWD 保持为用户工作对象目录
WORKSPACE_ROOT="$PWD"
test "$WORKSPACE_ROOT" != "$SKILL_ROOT" || { echo "WORKSPACE_ROOT 不能是技能安装目录" >&2; exit 2; }
```

列表客户端为 `scripts/rpa_dynamic_client.py`，详情客户端为 `scripts/rpa_dynamic_detail_client.py`。每次取数都先 `detail`/`schema` 获取实时 `platformCode`、`inParamJsonSchemaText` 或 `inParamList`，再把业务参数作为一个完整 JSON 用 `validate` 校验；`fetch` 会二次反查和校验，然后统一走异步 task/status、下载并解析 CSV。schema text 非空时不得读取 `inParamList`；平台值原样透传，不补 `_ACCOUNT_PASSWORD`。外层工具执行真实 `fetch` 时显式设置 3600 秒超时。

```bash
# 榜单连接器
python "$SKILL_ROOT/scripts/rpa_dynamic_client.py" detail
python "$SKILL_ROOT/scripts/rpa_dynamic_client.py" schema
python "$SKILL_ROOT/scripts/rpa_dynamic_client.py" list-accounts
python "$SKILL_ROOT/scripts/rpa_dynamic_client.py" validate --params-file config/rpa-list-params.json
python "$SKILL_ROOT/scripts/rpa_dynamic_client.py" fetch --shop-id "<shop_id>" \
  --params-file config/rpa-list-params.json \
  --output-dir "$WORKSPACE_ROOT/云图数据资源/example/rpa-list"

# 详情连接器
python "$SKILL_ROOT/scripts/rpa_dynamic_detail_client.py" detail
python "$SKILL_ROOT/scripts/rpa_dynamic_detail_client.py" schema
python "$SKILL_ROOT/scripts/rpa_dynamic_detail_client.py" validate --params-file config/rpa-detail-params.json
python "$SKILL_ROOT/scripts/rpa_dynamic_detail_client.py" fetch --shop-id "<shop_id>" \
  --params-file config/rpa-detail-params.json \
  --output-dir "$WORKSPACE_ROOT/云图数据资源/example/rpa-details"
```

```bash
# 未显式提供配置时，先核对继承环境的目标网关（不发网络请求）
python "$SKILL_ROOT/scripts/collector.py" runtime-check
python "$SKILL_ROOT/scripts/collector.py" list-accounts
python "$SKILL_ROOT/scripts/collector.py" validate --query-spec query.json
python "$SKILL_ROOT/scripts/collector.py" collect --shop-id "<shop_id>" --query-spec query.json --output-dir "$WORKSPACE_ROOT/云图数据资源/example"
# 请求图片时才提供 --highlight-spec；--highlight-mode off 与规则同时出现会被拒绝
python "$SKILL_ROOT/scripts/collector.py" collect --shop-id "<shop_id>" --query-spec query.json --highlight-mode on --highlight-spec highlights.json --output-dir "$WORKSPACE_ROOT/云图数据资源/example"
python "$SKILL_ROOT/scripts/collector.py" status --output-dir "$WORKSPACE_ROOT/云图数据资源/example"
python "$SKILL_ROOT/scripts/collector.py" retry-highlights --output-dir "$WORKSPACE_ROOT/云图数据资源/example"
python "$SKILL_ROOT/scripts/collector.py" build-facts --run-dir "$WORKSPACE_ROOT/云图数据资源/example"
# 阶段一采集/事实门禁通过后，生成离线第一阶段数据报告；默认写入 $WORKSPACE_ROOT/云图数据资源/example/overview/
python "$SKILL_ROOT/scripts/collector.py" render-overview --run-dir "$WORKSPACE_ROOT/云图数据资源/example"
# 需要显式指定报告目录时，目录必须位于运行目录内
python "$SKILL_ROOT/scripts/collector.py" render-overview --run-dir "$WORKSPACE_ROOT/云图数据资源/example" --output-dir "$WORKSPACE_ROOT/云图数据资源/example/overview-preview"
# render-overview 成功后停止，等待用户输入商业分析思路或商业问题；收到问题后才进入阶段二
python "$SKILL_ROOT/scripts/collector.py" workflow --run-dir "$WORKSPACE_ROOT/云图数据资源/example" \
  --business-question "找出曝光高但转化差的素材"
# 记录上一步返回的 analysis_id；当前对话模型返回 FactSelectionSpec JSON 后回放本地事实选择
python "$SKILL_ROOT/scripts/collector.py" workflow --run-dir "$WORKSPACE_ROOT/云图数据资源/example" \
  --business-question "找出曝光高但转化差的素材" \
  --analysis-id "<analysis_id>" \
  --fact-selection-result "$WORKSPACE_ROOT/云图数据资源/example/selection-result.json" \
  --output "$WORKSPACE_ROOT/云图数据资源/example/analysis/<analysis_id>/workflow.md"
# 当前对话模型返回 AnalysisResult JSON 后生成最终报告
python "$SKILL_ROOT/scripts/collector.py" workflow --run-dir "$WORKSPACE_ROOT/云图数据资源/example" \
  --business-question "找出曝光高但转化差的素材" \
  --analysis-id "<analysis_id>" \
  --analysis-result "$WORKSPACE_ROOT/云图数据资源/example/analysis-result.json" \
  --output "$WORKSPACE_ROOT/云图数据资源/example/analysis/<analysis_id>/workflow.md"
# 历史运行仍可使用旧 AnalysisInput 入口
python "$SKILL_ROOT/scripts/collector.py" analyze --run-dir "$WORKSPACE_ROOT/云图数据资源/example" --input analysis-input.json --output "$WORKSPACE_ROOT/云图数据资源/example/analysis.md"
# 历史运行仍可使用旧 AnalysisSpec 入口
python "$SKILL_ROOT/scripts/collector.py" analyze --run-dir "$WORKSPACE_ROOT/云图数据资源/example" --spec analysis-spec.json --output "$WORKSPACE_ROOT/云图数据资源/example/analysis.md"
# analyze 未传 --analysis-result 时只生成宿主交接包，不生成报告；当前对话模型返回 JSON 后回放
python "$SKILL_ROOT/scripts/collector.py" analyze --run-dir "$WORKSPACE_ROOT/云图数据资源/example" --input analysis-input.json \
  --analysis-result "$WORKSPACE_ROOT/云图数据资源/example/model-result.json" --output "$WORKSPACE_ROOT/云图数据资源/example/analysis.md"
python "$SKILL_ROOT/scripts/check_runtime_sync.py" --target .system/skills/custom/yuntu-meta-skill
```

采集或后处理返回 `partial`、`failed` 或非零退出码后，默认动作是停止并保留现场。RPA 失败项不自动重试，也不提供失败项或 unresolved 项的 RPA 重提命令；先向用户说明失败事实和已有落盘数据。`retry-highlights` 只处理本地已落盘详情的图片后处理，不调用 RPA，只有用户明确选择恢复后才执行。用户在当前会话表达过暂停、停止或质疑重跑时，后续外部采集动作必须再次取得明确授权。只读诊断、状态查询和本地完整性核对可以直接执行。

### 运行环境与鉴权

用户在当前任务中明确指定的网关和凭证优先于继承环境。提示词中的赋值不会自动改变 shell 环境；必须实际传入采集进程，不能仅检查变量存在就声称已采用用户配置。凭证可来自平台注入或用户主动提供，不能从无关日志、历史产物或配置文件搜集凭证。`CODEX_SESSION_ID` 是 Codex 任务标识，不能作为网关凭证。

用户显式提供配置时，使用 `--runtime-config-stdin`，通过标准输入传入**一行 JSON**：字段仅限 `ENV_BACKEND_HOST`、`YUCE_AUTHORIZATION`、`YUCE_SESSION_ID`、`YCSESSIONID`，值均为字符串；前两个必填，后两个至少一个非空。这是完整配置替换，不与继承凭证混合。只有用户明确说几项值相同时才复用同一个值，不能自行推断。粘贴内容中的 Markdown 链接、转义下划线和 `&#x20;` 是格式，先还原为实际变量名、URL 和值，不能作为凭证字符直接传入。

```bash
# 全局参数放在子命令前；URL 换成用户明确指定的网关，命令中不放凭证
python "$SKILL_ROOT/scripts/collector.py" --runtime-config-stdin --expected-gateway https://gateway.example/api list-accounts
python "$SKILL_ROOT/scripts/collector.py" --runtime-config-stdin --expected-gateway https://gateway.example/api collect --shop-id "<shop_id>" --query-spec query.json --output-dir "$WORKSPACE_ROOT/云图数据资源/example"
```

终端交互模式会关闭输入回显，宿主通过终端标准输入发送 JSON 行；管道模式从标准输入读取一行。不要用含真实凭证的 `echo`、heredoc、命令参数或落盘文件构造输入。每次新的 `collect` CLI 调用都需要重新传入同一组任务配置；一次调用不会修改全局环境或自动配置后续调用。同一次采集的榜单、详情提交和轮询会共享该配置。

未显式提供配置时保留平台环境兼容路径。`runtime-check` 只显示目标网关、配置来源、变量存在性，不验证认证；RPA 命令也会向 stderr 输出同样的脱敏预检信息，stdout 保持原业务 JSON。用户指定网关时加 `--expected-gateway`，不匹配就会在请求前失败。不要回显凭证或以长度相同判断值相同。

未知 `shop_id` 先查询账号。鉴权失败先看实际网关、配置来源、HTTP 状态、业务 code 与 traceId；已显式提供配置但尚未应用时，先正确传入再重试账号查询。网关 `authentication_failed` 不证明巨量云图网页登录失效；`credential_expired` 表示当前目标网关报告凭证过期。正确配置下仍失败时报告证据与缺少的输入，不能让用户盲目重登云图，也不能反复请求同一套错误配置。保留现有 Cookie 兼容协议：优先使用显式 `YCSESSIONID`，缺省时使用 `YUCE_AUTHORIZATION`。

## 产物与恢复

新运行统一写入用户工作对象目录下的 `$WORKSPACE_ROOT/云图数据资源/`，技能安装目录只保留代码、配置与参考资料。所有会写文件的入口都必须显式提供输出路径，并拒绝技能安装目录内的目标；两个动态 RPA 客户端也必须显式传 `--output-dir`。原有技能内 `runs/`、`RPA数据汇总/`、`云图数据资源/` 仅作为历史只读兼容目录，不搬动、不覆盖；如需恢复或继续生成本地产物，先完整复制到工作对象目录并从副本接续。每个运行目录包含解析后的配置、`raw-csv/`、`normalized/`、`batch-manifest.json`、`run-summary.json`，以及仅在请求图片时存在的 `highlights-manifest.json` 与 JPEG。详情异步提交会立即在 manifest 的 `taskRuns` 登记 `task_group_id`；同一次采集只轮询已登记任务，临时网络异常保留为 unresolved 并停止，不重新提交 RPA。关闭图片时其状态为 `not_requested`，不是缺包；图片失败不改变已选源素材，但会在第一阶段回执中单独记录。经用户明确授权后，`retry-highlights` 可从 `partial` 或 `failed` 恢复到采集态，只处理已落盘详情对应的缺失高光帧，再重新构建事实包；它不重新提交榜单或详情 RPA。`retry-highlights` 仍是显式第一阶段恢复，第二阶段绝不触发它。

`collect` 和 `retry-highlights` 在更新运行产物后会自动构建 `facts/`，并输出 facts 清单路径、coverage 和 ready 回执；只有采集门禁、四类事实包和品牌分类都完成时才进入 `ready_for_analysis`，阶段一不会自动分析。`status` 会通过 `facts_status` 报告 `complete`、`missing` 或 `invalid`，并返回当前工作流状态。采集完成后也可使用 `build-facts` 将现有运行目录整理为商业分析的事实底座，该命令只读取本地 `normalized/`、`raw-csv/`、`highlights-manifest.json` 和运行摘要，不调用 RPA 或网络，并在 `facts/` 生成素材榜单、人群、脚本、高光帧四类事实包及 `manifest.json`。事实包只做来源字段整理和可用性标记，不生成商业洞察；脚本为空时会保留 `source_empty` 原因。

### 第一阶段报告与停止点

当 `status` 返回 `status=ready_for_analysis` 且 `facts_status=complete` 后，必须对同一 `run_dir` 执行 `render-overview`。该命令只读取已落盘运行数据和注册表，不重新取数、不重新规范化、不重新分类、不启动商业分析；它会校验 `run-summary.json` 中榜单源文件的声明路径、文件大小、SHA-256 和记录数，并将已验证的高光帧/详情图片复制到报告目录。

报告默认生成在 `$WORKSPACE_ROOT/云图数据资源/example/overview/`，核心产物为 `$WORKSPACE_ROOT/云图数据资源/example/overview/overview-data.json` 和 `$WORKSPACE_ROOT/云图数据资源/example/overview/index.html`，必要时附带 `assets/` 下的本地图片。`overview-data.json` 是带来源引用、哈希、可用性和缺口信息的事实投影；`index.html` 是离线数据工作台，展示素材榜单、人群数据、脚本/内容公式、高光帧和已执行详情范围。报告仅展示事实与确定性统计，不得加入 AI 分析、商业结论、行动建议或猜测字段含义。

如果报告生成失败，保留运行目录和失败证据，先修复事实包或源文件校验问题；不得绕过校验进入阶段二。报告生成成功后，阶段一即完成，交付报告路径、事实包路径和数据缺口，并等待用户输入商业分析思路或商业问题。`render-overview` 不会改变 `ready_for_analysis` 状态；只有收到有效分析问题后才进入 `workflow` 或兼容的 `analyze`。

事实包生成时会从本轮 `list_context.brands`（或其 `pre_input.brands`）建立严格的运行时品牌候选范围，不会扩展默认品牌表。标题分类仅对候选品牌执行 Unicode NFKC、`casefold()` 和连续字符串匹配；规范名中的 `/` 表示别名，支持多品牌同时命中，并在 `brand_classification` 中保留 `matchedBrands` 与 `match_tokens` 审计证据。未命中或候选范围缺失时归为 `未知品牌`；`九阳豆浆` 仅支持显式受控的“九阳…豆浆”变体，单独“九阳”不命中。分类不依据品类、功效、标签或画面推断，四类事实包按 `material_id` 传播同一快照。

通过 `.system/skills/custom/yuntu-meta-skill` 执行前，保持工作目录为用户工作对象目录，并运行 `check_runtime_sync.py` 校验运行副本。校验会比较采集器、两个动态 RPA 客户端、运行目录门禁、事实包、第一阶段报告和分析编排模块的 SHA-256，并确认目标 `collector.py --help` 包含 `build-facts` 与 `render-overview`；校验失败时先同步源码脚本再执行。同步只允许写入技能源码和直接依赖，不得复制凭证、历史 `runs/`、`$WORKSPACE_ROOT/云图数据资源/`、`.system/sessions/` 或报告数据。

## 商业分析编排

进入阶段二时必须显式提供 `AnalysisInput`（自然语言问题或结构化 JSON），并选择一个或多个分析模块。`sections` 可选 `material_ranking`、`audience`、`script`、`highlight_frames`；`business_question` 必填。仅选择模块、品牌/素材范围或指标时返回 `analysis_input_required` 并保持 `ready_for_analysis`，不生成任何分析产物。自然语言问题保留原文并标准化；`business_question_source` 为用户问题时记录 `user`，只有用户明确确认系统默认问题时才允许记录 `user_confirmed_default` 且 `user_confirmed: true`。`material_filter.rank_range` 必须位于 1..1000；可选 `brand_filter` 只能取当前 facts manifest 的候选品牌或 `未知品牌`，不允许模型或调用方扩展范围。只有 `ready_for_analysis`（或可验证的历史事实包兼容状态）允许启动分析；未就绪、缺包、未知品牌/素材/指标均返回校验错误。编排器只加载所选事实包，先校验 manifest、包路径、记录数和源文件 SHA-256，再生成带 `fact_refs` 的 PromptPacket。阶段二不重新采集、不重新规范化、不重新分类。

模型结果可通过 `--analysis-result` 传入，作为当前对话模型响应的离线回放/测试入口；未传入时命令只落盘 `*.model-analysis-request.json` 和 `*.prompt-packet.json`，返回 `awaiting_model_analysis` 宿主交接回执，不生成保守分析、结果或报告。宿主协议为 `yuntu-current-conversation-model-v2`：当前对话模型读取 `host_context`，只返回 `AnalysisResult` JSON（对象或 `{\"results\": [...]}`），再用同一运行目录和 `--analysis-result` 恢复。技能脚本不调用外部模型 API，也不启动独立模型。每条 `findings` 结论必须包含可解析的 `fact_refs`、合法的模块、`type` 和 `confidence`。`source_empty` 只能进入 `gaps`；当前脚本字段为空时不得用标题或标签代替脚本。`selection_group.brand_name` 为空且 `brand_classification.source=runtime_title_rule` 时，相关品牌结论必须标记为推断、降低置信度并填写品牌代理说明；标签关联和高光解释不得表述为因果。分析不依赖事后生成的 `fact-summary.json`。

`analyze` 在等待模型时旁写 `<stem>.model-analysis-request.json` 和 `<stem>.prompt-packet.json`；模型结果校验通过后才在 `--output` 写入 Markdown 报告，并旁写 `<stem>.analysis-result.json`。Markdown 以核心结论和行动建议开头，随后按 `material_ranking`、`audience`、`script`、`highlight_frames` 的业务顺序展示事实包，作为无外部依赖的兜底交付；HTML 的布局、组件与图表类型不固定，可按用户问题自由设计。正文使用 `[依据1]` 等短证据编号，不展示 finding 类型、置信度或完整 `fact_refs`；附录 A 直接展示数据对象与真实业务数值，附录 B 在结论、可信度和依据之外展示可核对的证据数据。完整 `fact_refs` 仅放在折叠技术追溯区。历史 `AnalysisResult` 缺少展示专用字段时仍按现有 `findings`、`gaps`、`next_questions` 渲染。结果校验失败时只保存包含 `code`、`path`、`message`、`suggestion` 的 `<stem>.analysis-error.json`，保持运行可重试且不生成报告。

`fact-selection-request.json.host_context.fact_catalog.packages.*.projectable_fields` 是每个事实包可直接使用的扁平字段清单，包含原始字段、业务名称、可用记录数、值类型和支持的本地聚合；构造 FactSelectionSpec 前先一次性读取该清单，不要靠校验报错逐字段试探。若仍填入未知字段，错误会回带该事实包的合法字段列表，收到一次错误后应同时核对本次选择中的全部字段再重试。

第二阶段模型请求中的 `host_context.report_presentation_guidance` 是非阻断式呈现建议，不新增模型轮次，也不因图表数量、样式或个别字段无中文标签而判失败。证据索引应展示素材名称或榜单位置、业务字段名称和真实数据；结论审计除依据编号外还应展示对应证据的真实数据参考。HTML 报告应在两部分各选择合适的可视化：有可比较业务指标时优先展示真实指标对比，不可比较时可展示证据覆盖、结论类型或可信度，并明确数据缺口。不得把事实路径、原始字段名或只有编号的表格作为用户侧主要内容。

用户要求 HTML 时，先一次性确定信息架构、所需数据、组件和文件清单，再集中生成完整交付物；仅在出现明确校验失败或用户反馈后局部修改。不得把“先写入口、再反复补 JS/CSS/manifest”作为默认工作流，也不得为了避免修改而固定报告版式。

新流程优先使用 `workflow`：第一次模型交接只生成 `AnalysisIntent + FactSelectionSpec`，技能在本地从已落盘 `facts/` 选择记录；第二次模型交接只分析同一 `analysis_id` 目录下的 `selected-fact-context.json`。两轮都使用当前会话内模型，阶段二不生成或修改任何 RPA 入参，也不重新采集、规范化或品牌分类。恢复事实选择或提交模型结果时必须显式传入首次回执中的 `--analysis-id`；报告输出必须位于对应 `analysis/<analysis_id>/`，未传 `--output` 时默认使用其中的 `workflow.md`。报告额外展示“用户问题 → AnalysisIntent → FactSelectionSpec → 实际选中记录 → 数据缺口 → AI 结论 → fact_refs”链路。不存在的 ROI/GMV 等字段和脚本 `source_empty` 必须显式作为缺口；真实运行中的 1000 条榜单及 306 条未知品牌限制会进入审计。

## 从完整运行创建新 Skill

用户在完成榜单与详情采集、事实校验、分析与报告后要求固化本流程时，先以**本次已成功的运行回执**为依据：记录授权账号的字段类型（不保存凭证）、QuerySpec/HighlightSpec、`run-summary.json` 与事实包 manifest、使用的 `analysis_id`、事实选择、已验证模型结果、最终报告及缺口。把行业、授权账号、周期、筛选、详情数和分析问题做成新 Skill 的入参；不要写死客户 ID、日期、路径、样本结论或“1000 条均有详情”的假设。新 Skill 保留“榜单→详情→事实校验→分析→报告”的门禁、`analysis_id` 续跑和失败现场，不用旧报告冒充本轮结果。

派生 Skill 的自定义日期表单须声明 `max_policy: t_plus_4`，说明“前 4 天及以前”，但表单只是第一道提示。新 Skill 的每条自定义日期实时取数路径在提交榜单或详情 RPA **之前**都必须调用随包交付的 `scripts/date_policy.py` 的 `validate_custom_period`（或委托本元技能的 `QuerySpec`/`collector.py collect`），并让非零退出阻断网络请求。若新 Skill 独立安装，须将该日期校验代码与调用点、测试一同纳入自己的包；只复制表单或提示词不算完成。自定义日报默认统计日可设为北京时间前 4 天；明确请求较晚日期时返回可用上限并请用户改选，不自动替用户改日。`LAST_7_DAYS`/`LAST_30_DAYS` 继续传原生周期枚举，不伪造自定义日期。可用命令：`python "$SKILL_ROOT/scripts/date_policy.py" --start-date YYYYMMDD --end-date YYYYMMDD`。

交付派生包前至少验证北京时间边界 T-4 通过、T-3/今天/未来拒绝、369 天下界及 45 天跨度、非法日期不会提交任何 RPA；检查新包中的脚本、表单、依赖、报告资源和回执路径均存在且可从干净解包目录运行。若引入直接连接器调用，不得绕过日期门禁、账号授权与事实校验。
