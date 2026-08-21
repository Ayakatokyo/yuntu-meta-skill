# 云图-行业灵感-行业内容榜列表

## 固定元数据

- `function_code`: `rpa.conn.juliang.yt.industry.content.rankings.list`
- `platform`: `RPA_JULIANG_YT_ACCOUNT_PASSWORD`
- `data_source_type`: `rpa`

## 适用场景

采集巨量云图行业灵感页行业内容榜视频列表，支持按行业、时间、品牌范围、品牌、年龄、性别、八大人群和榜单限制筛选。

## 入参说明

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

- 按列表响应顺序选择最先出现的唯一数字型 `material_id`
- 以 `candidate_top_n` 建立候选池
- 为后续详情拉取和分析生成 `normalized/list-records.json`
