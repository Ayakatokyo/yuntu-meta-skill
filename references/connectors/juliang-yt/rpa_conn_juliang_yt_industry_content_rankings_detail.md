# 云图-行业内容榜-素材详情秒级拆解（历史读取）

> 本页仅描述历史批次的旧 `detail` function code、`date_range_type` 和旧结果格式。新采集必须使用 [details 异步连接器](rpa_conn_juliang_yt_industry_content_rankings_details.md)，不会自动回退到本页协议。

## 历史标识

- `function_code`: `rpa.conn.juliang.yt.industry.content.rankings.detail`（仅历史）

旧批次中记录的平台和参数只用于解释既有文件，不能作为新采集配置。新采集的平台、输入契约和输出字段全部从连接器详情实时读取。

## 适用场景

采集巨量云图行业内容榜中指定素材的秒级拆解指数，包括点赞、流失、点击、互动、评论等趋势，以及详情页视频链接。

## 入参说明

- `material_id`
- `date_range_type`（仅历史）
- `custom_start_date`
- `custom_end_date`

## 当前技能附加行为

- `material_id` 始终从当前列表连接器结果的全局前 `target_top_n` 条中选择，不接受外部覆盖或排名更低素材补位
- 选择组字段仅用于校验详情归属，不能让详情数量按品牌或触点分组扩张
- 详情失败时记录到 `rejectedMaterials`，后续可通过 `retry-failed` 定向重试
- 成功结果会写入 `normalized/detail-records/<material_id>.json`，供分析事实包和最终报告使用
