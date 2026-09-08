# 云图-行业内容榜-素材详情异步任务

## 固定元数据

- `function_code`: `rpa.conn.juliang.yt.industry.content.rankings.details`
- `platform`: `RPA_JULIANG_YT_ACCOUNT_PASSWORD`
- `data_source_type`: `rpa`
- 详情参数：`material_id`、`date_type`、`custom_start_date`、`custom_end_date`

## 调用协议

1. `POST /adg/v1/agent/fetch/tasks` 提交任务，响应必须为 `success=true` 且 `data.task_group_id` 非空。
2. `POST /adg/v1/agent/fetch/tasks/status` 使用 `task_group_id` 轮询。
3. `pending`/`running` 继续轮询；`completed`/`partial_success` 只表示远端完成，仍需下载或解包、写入 raw/normalized 并校验身份和周期；`failed` 或未知状态拒绝。
4. 恢复同一输出目录时只轮询 manifest `taskRuns` 已登记的 task id，不重新提交。

## 结果格式

完成态可返回 `data.files`、`data.result_content.files`、`files`、`payload` 或 `records`。文件必须有唯一非空 `fileUrl`；记录必须是非空数组。未完成、失败、空文件地址不能被当成业务记录。

## 新详情字段

规范化器读取 `coreData`、`audiencePortrait`、`secondTrend`、`contentFormula`、`creativeBreakdown` 和 `videoScript`。五个 `secondTrend` key 映射为点赞、流失、点击、互动、评论 canonical 趋势；根 `materialId` 与 `coreData.objectId` 冲突、`dateType` 与请求 `date_type` 不一致时拒绝。
