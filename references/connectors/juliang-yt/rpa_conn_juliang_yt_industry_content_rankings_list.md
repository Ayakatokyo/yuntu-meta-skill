# 云图-行业灵感-行业内容榜列表

## 唯一静态身份

- `function_code`: `rpa.conn.juliang.yt.industry.content.rankings.list`

`platformCode`、输入 schema/list 契约和输出字段必须在运行时由连接器详情接口读取。本文字段只保留业务语义参考，不是实际传参的权威定义。

## 适用场景

采集巨量云图行业灵感页行业内容榜视频列表，支持按行业、时间、品牌范围、品牌、年龄、性别、八大人群和榜单限制筛选。

## 历史业务语义参考

- `industry`
- `time_range_type`
- `custom_start_date`
- `custom_end_date`
- `ages`
- `genders`
- `crowd_groups`
- `brand_scope_type`
- `brands`
- `ranking_limit_type`

其中 `ages`、`genders`、`crowd_groups` 在当前技能中只做格式校验，兼容平台实际值和后续扩展值。

## 当前技能附加行为

- 完整持久化平台返回的 Top1000 列表到 `normalized/list-records.json`
- 按规范化列表的全局 `rank` 选择前 `target_top_n` 个唯一数字型 `material_id` 进入详情阶段
- `candidate_top_n` 固定为 1000，仅表示完整列表保留容量，不能扩大详情选择范围
- 不按品牌、触点或选择组拆分 Top N；选择组只作为后续详情归属校验上下文
