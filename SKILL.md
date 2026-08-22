---
name: yuntu-configurable-collection
description: 通过结构化查询配置采集巨量云图行业内容榜、素材秒级详情和可配置高光帧。适用于需要重复运行、校验口径或生成独立采集技能底座的场景。
argument_hint: 提供 query-spec.json 与 highlight-spec.json，或先将对话需求转换为两份配置并回显确认。
---

# 可配置云图采集

该技能只负责榜单、详情和高光帧资产，不生成商业分析、模型洞察或报告。

## 输入

对话入口必须先生成两份 JSON，并向用户回显确认；文件入口直接读取已保存配置。两种入口必须经过相同的解析器，随后落盘为运行目录中的 `resolved-query-spec.json` 和 `resolved-highlight-spec.json`。

`query-spec.json` 支持行业、近 7 天/近 30 天/自定义日期、年龄、性别、八大人群、品牌范围、四类榜单指标、目标素材数和候选池数量。自定义日期必须是闭区间并遵循云图可用日期与跨度限制。

`highlight-spec.json` 支持点赞、流失、点击、互动、评论指数五个维度；每个维度可独立选择 `local_peaks` 或 `absolute_max`，并指定正整数帧数。第一版未知字段和策略直接拒绝。

## 执行

```bash
python scripts/collector.py list-accounts
python scripts/collector.py validate --query-spec query.json --highlight-spec highlights.json
python scripts/collector.py collect --shop-id "<shop_id>" --query-spec query.json --highlight-spec highlights.json --output-dir runs/example
python scripts/collector.py status --output-dir runs/example
python scripts/collector.py retry-failed --shop-id "<shop_id>" --output-dir runs/example
python scripts/collector.py retry-unresolved --shop-id "<shop_id>" --output-dir runs/example
```

固定连接器和运行时凭证由平台环境提供；不要把凭证写入命令、配置、清单或输出。未知 `shop_id` 先运行 `list-accounts`。

## 产物与恢复

运行目录包含解析后的配置、`raw-csv/`、`normalized/`、`batch-manifest.json`、`run-summary.json`、`highlights-manifest.json` 和 `highlights/` JPEG 资产。配置、shop ID 或采集参数变化时必须使用新目录。`retry-failed` 只重试拒绝详情，`retry-unresolved` 只重试未持久化详情；同一批次的重试会沿用保存的高光策略。
