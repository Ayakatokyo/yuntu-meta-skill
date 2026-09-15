# 平台知识地图：巨量云图

本页用于把“巨量云图 / 行业灵感 / 行业内容榜 / 素材详情秒级拆解”路由到当前技能内部的列表连接器和新版详情任务连接器知识页。

## 连接器入口

- 列表：`references/connectors/juliang-yt/rpa_conn_juliang_yt_industry_content_rankings_list.md`
- 新详情：`references/connectors/juliang-yt/rpa_conn_juliang_yt_industry_content_rankings_details.md`
- 历史详情读取：`references/connectors/juliang-yt/rpa_conn_juliang_yt_industry_content_rankings_detail.md`

## 说明

- connector code 是唯一静态身份；平台必须从详情接口的 `platformCode` 读取并原样透传
- 不允许外部覆盖 `function_code`
- 列表和新详情分别先读取实时详情与 schema，再校验完整业务 JSON，并统一使用异步 fetch task/status；旧详情页只服务历史批次读取
- 当前技能在两个连接器结果之上增加了完整 Top1000 列表持久化、全局 Top N 详情选择、规范化和五指标截帧资产；前 N 条详情失败不会由排名更低的素材补位
