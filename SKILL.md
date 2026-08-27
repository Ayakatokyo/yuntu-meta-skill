---
name: yuntu-meta-skill
description: 通过结构化查询配置采集巨量云图行业内容榜、素材秒级详情和可配置高光帧。适用于需要重复运行、校验口径或生成独立采集技能底座的场景。
argument_hint: 输入行业、时间周期、榜单指标、详情素材数、年龄/性别/八大人群/品牌筛选，以及封面和可选高光指标的截帧策略与帧数；生成并采集 QuerySpec、HighlightSpec 及高光帧资产。
metadata:
  pre_input: 请采集云图行业内容榜单和素材高光帧，行业是 ____（必填）；时间周期是 ____（自定义起止日期，默认近7天）；截取方式是 ____（曝光量TOP1000、CTRTOP1000、互动率TOP1000或完播率TOP1000）；品牌范围是 ____（全行业，或指定3至10个品牌）；需要执行详情拆解的素材数为 ____（正整数，默认10）；年龄是 ____（可选，留空不过滤）；性别是 ____（可选，留空不过滤）；八大人群是 ____（可选，留空不过滤）。高光帧筛选：是否保留封面帧（是/否）；高光指标至少选择一项，可从点赞、流失、点击、互动、评论五项中选择；每个已选指标可按波峰或指标大小截取，并指定帧数。（如：保留封面帧，点赞指数取指标值最高的前 2 帧，流失指数取局部峰值/波峰 2 帧。）
---

# 可配置云图采集

该技能只负责榜单、详情和高光帧资产，不生成商业分析、模型洞察或报告。

## 输入

自然语言入口必须从同一句请求解析出两份 JSON：`QuerySpec`（行业、周期、筛选、榜单指标、详情素材数）和 `HighlightSpec`（封面及五项指标的策略/帧数）。文件入口直接读取已保存配置；两种入口使用同一解析器，成功后立即落盘并执行，失败则反馈具体字段错误。

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
```

固定连接器和运行时凭证由平台环境提供；不要把凭证写入命令、配置、清单或输出。未知 `shop_id` 先运行 `list-accounts`。

## 产物与恢复

运行目录包含解析后的配置、`raw-csv/`、`normalized/`、`batch-manifest.json`、`run-summary.json`、`highlights-manifest.json` 和 `highlights/` JPEG 资产。配置、shop ID 或采集参数变化时必须使用新目录。前 N 条中的详情失败会单独落盘，不能用排名更低的素材补位。只有所有目标详情成功且按保存的高光策略生成的帧都可用时，运行才是 `success`；高光帧缺失或不可用时为 `partial`。`retry-failed` 只重试拒绝详情，`retry-unresolved` 只重试未持久化详情，`retry-highlights` 只重建缺失或不可用的高光帧，不重新请求榜单或详情；同一批次的重试会沿用保存的高光策略。
