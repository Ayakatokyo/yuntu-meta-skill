# 云图-行业内容榜-素材详情异步任务

## 唯一静态身份

- `function_code`: `rpa.conn.juliang.yt.industry.content.rankings.details`

`platformCode`、输入 schema/list 契约和输出字段必须在运行时由连接器详情接口读取。`material_id`、`date_type`、`custom_start_date`、`custom_end_date` 仅作为历史业务语义参考，不能替代实时契约。

## 调用协议

1. 先调用 `/dcConnector/v3/listByConnectorCode` 读取详情并按实时契约校验完整业务 JSON。
2. `POST /adg/v1/agent/fetch/tasks` 提交任务，响应必须为 `success=true` 且 `data.task_group_id` 非空。
3. `POST /adg/v1/agent/fetch/tasks/status` 使用 `task_group_id` 轮询。
4. `pending`/`running` 继续轮询；`completed`/`partial_success` 只表示远端完成，仍需下载或解包、写入 raw/normalized 并校验身份和周期；`failed` 或未知状态拒绝。
5. 恢复同一输出目录时只轮询 manifest `taskRuns` 已登记的 task id，不重新提交。

## 结果格式

完成态可返回 `data.files`、`data.result_content.files`、`files`、`payload` 或 `records`。文件必须有唯一非空 `fileUrl`；记录必须是非空数组。未完成、失败、空文件地址不能被当成业务记录。

## 新详情字段

规范化器读取 `coreData`、`audiencePortrait`、`secondTrend`、`contentFormula`、`creativeBreakdown` 和 `videoScript`。五个 `secondTrend` key 映射为点赞、流失、点击、互动、评论 canonical 趋势；根 `materialId` 与 `coreData.objectId` 冲突、`dateType` 与请求 `date_type` 不一致时拒绝。

## 首批 CSV 保护入口

详情实际取数通过 `collector.py collect` / `yuntu_batch.fetch_batch` 调度，首次最多 3 条，首批零有效 CSV 暂停后续所有 RPA，并提示入参可能有问题；未知状态只核实已登记任务。`rpa_dynamic_detail_client.py` 的 `detail`、`schema`、`validate` 保留用于诊断，`fetch`（含 `--no-download`）拒绝直提交，防止循环单素材调用绕过批次门禁。动态榜单客户端也先检查输出目录及所属运行的暂停记录。
