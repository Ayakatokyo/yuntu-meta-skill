# 云图-行业内容榜-素材详情秒级拆解

## 固定元数据

- `function_code`: `rpa.conn.juliang.yt.industry.content.rankings.detail`
- `platform`: `RPA_JULIANG_YT_ACCOUNT_PASSWORD`
- `data_source_type`: `rpa`

## 适用场景

采集巨量云图行业内容榜中指定素材的秒级拆解指数，包括点赞、流失、点击、互动、评论等趋势，以及详情页视频链接。

## 入参说明

- `material_id`
- `date_range_type`
- `custom_start_date`
- `custom_end_date`

## 当前技能附加行为

- `material_id` 始终从当前列表连接器结果的全局前 `target_top_n` 条中选择，不接受外部覆盖或排名更低素材补位
- 选择组字段仅用于校验详情归属，不能让详情数量按品牌或触点分组扩张
- 详情失败时记录到 `rejectedMaterials`，后续可通过 `retry-failed` 定向重试
- 成功结果会写入 `normalized/detail-records/<material_id>.json`，供分析事实包和最终报告使用
