# 云图可配置采集元技能阶段一列表 RPA 测试交接摘要

## 交接目的

当前对话已完成第一 RPA“素材列表筛选”的自然语言场景测试。下一轮对话进入第二 RPA“素材详情”测试。本摘要记录已验证结论、运行产物、已知异常和建议的详情测试入口，不需要重新执行列表场景或重新推导 QuerySpec 边界。

## 当前结论

第一 RPA 列表筛选已验证可用：成功场景均返回 1000 条素材，原始 CSV 和规范化列表均已落盘，列表上下文校验通过。所有本轮测试均只调用列表连接器，没有调用详情连接器。

E 场景（24-30 岁年龄筛选）曾连续尝试，失败均发生在列表结果文件获取阶段；不能据此判定筛选参数错误。B 场景在相同账号和 OSS 链路下多次成功，说明 OSS 并非整体不可用。

## 独立仓库与运行信息

仓库：`/Users/shuzida/Desktop/FDE客户/小仙炖/yuntu-configurable-collection`

当前分支：`main`

最近代码提交：`ce75f98 修复：兼容平台点击率榜单上下文别名`

已确认的 `shop_id`：`r4uKddk94v`

运行凭证通过环境变量注入：`ENV_BACKEND_HOST`、`YCSESSIONID`、`YUCE_AUTHORIZATION`。凭证值没有写入本摘要、配置或运行产物。

## 第一 RPA 自然语言测试结果

所有成功场景均以自然语言描述作为测试输入，再转换为 QuerySpec 和 RPA 扁平参数；没有把预先写好的 JSON 直接当作用户入口。

| 场景 | 自然语言条件摘要 | 结果 |
|---|---|---|
| A | 食品饮料近七天、全行业、曝光量 TOP1000 | 成功，1000 条 |
| B | 食品饮料近七天、全行业、点击率 TOP1000 | 成功，1000 条 |
| C | 食品饮料近三十天、全行业、曝光量 TOP1000 | 成功，1000 条 |
| D | 食品饮料近七天，小仙炖/燕之屋/五个女博士，曝光量 TOP1000 | 成功，1000 条 |
| E | 食品饮料近七天、24-30 岁、曝光量 TOP1000 | 失败：OSS CSV 下载 `SSL EOF`；后续网关 unsuccessful；均未落盘 |
| F | 食品饮料近七天、女性、曝光量 TOP1000 | 成功，1000 条 |
| G | 食品饮料近七天、精致妈妈、曝光量 TOP1000 | 成功，1000 条 |
| H | 三品牌 + 女性 + 精致妈妈、互动率 TOP1000 | 成功，1000 条 |
| I | 食品饮料 2026-08-01 至 2026-08-05、完播率 TOP1000 | 成功，1000 条 |

B 的 OSS 对照结果：

- `runs/nl-b-food-beverage-last7-all-ctr-oss-check-20260823`：成功，1000 条。
- `runs/nl-b-food-beverage-last7-all-ctr-retry-20260824`：成功，1000 条。
- 两次均 `contextVerified=true`，`detailExecuted=false`。

推荐后续详情测试优先使用 B 的成功列表产物，避免把 E 的下载异常混入详情问题。

## 重要运行产物

成功列表场景的目录均位于仓库 `runs/` 下，目录名与场景对应。例如：

- A：`runs/nl-a-food-beverage-last7-all-exposure`
- B 最新成功重试：`runs/nl-b-food-beverage-last7-all-ctr-retry-20260824`
- D：`runs/nl-d-food-beverage-last7-specified-brands-exposure`
- H：`runs/nl-h-food-beverage-last7-brands-female-refined-mom-interaction`
- I：`runs/nl-i-food-beverage-custom-20260801-20260805-completion`

每个成功列表目录包含：

- `raw-csv/list.csv`
- `normalized/list-records.json`
- `list-only-manifest.json`

E 的失败记录：

- `runs/nl-e-food-beverage-last7-age24-30-exposure/list-only-manifest.json`
- `runs/nl-e-food-beverage-last7-age24-30-exposure-retry-20260823/list-only-manifest.json`
- `runs/nl-e-food-beverage-last7-age24-30-exposure-retry-20260823-attempt2/list-only-manifest.json`

## 第二 RPA 详情接口契约

详情连接器：

- Function code：`rpa.conn.juliang.yt.industry.content.rankings.detail`
- 平台：`RPA_JULIANG_YT_ACCOUNT_PASSWORD`
- 数据源类型：`rpa`

基础详情参数：

```json
{
  "material_id": "7671214258320982035",
  "date_range_type": "LAST_7_DAYS"
}
```

可用的 `date_range_type`：

- `LAST_7_DAYS`
- `LAST_30_DAYS`
- `CUSTOM`，此时必须提供 `custom_start_date` 和 `custom_end_date`

详情校验要求：

- `material_id` 必须是纯数字字符串，必须来自已成功落盘的列表记录。
- 非 `CUSTOM` 不能带自定义日期字段。
- `CUSTOM` 的结束日期不能早于开始日期；从公共 QuerySpec 入口执行时还应遵守云图日期范围和跨度限制。
- 若列表记录存在品牌/触点选择组，批处理详情请求会一并携带 `selectionGroupId`、品牌和触点字段，用于详情归属校验；直接调用时应优先沿用列表记录中的选择组信息。

详情处理链路会：调用网关、解析记录或 CSV 文件、落盘原始详情、规范化详情记录，并校验返回的素材 ID 与请求 ID 一致。完整批次还会继续下载视频、抽帧并生成高光资产；本轮下一阶段建议先把详情请求和详情落盘单独验证，再验证高光后处理。

## 已有详情链路证据与风险

历史真实运行目录：

`runs/real-e2e-20260822-top2`

该运行已证明详情调度和高光链路可以工作，但不是全通过：4 条候选中 3 条提交，2 条成功持久化，1 条被拒绝，1 条取消；失败详情原因是 `RPA gateway payload must be a record list`。因此下一阶段需要重新验证详情返回格式，不能把历史批次标为详情 E2E 全通过。

历史成功详情素材 ID：

- `7655628765662494726`
- `7671196610973990953`

对应详情文件和高光文件可在上述真实运行目录中查看，但新测试应优先从最新成功 B 列表的 `normalized/list-records.json` 选择素材，确保列表和详情日期条件一致。

## 新对话建议执行顺序

1. 先读取本摘要，确认运行环境变量已注入；不要把凭证写入文件或命令产物。
2. 读取 B 最新成功列表：`runs/nl-b-food-beverage-last7-all-ctr-retry-20260824/normalized/list-records.json`。
3. 从前 1 条或 2 条记录中取得 `material_id`，先设计自然语言详情场景并回显解析结果，例如：

   > 查询素材 7671214258320982035 在食品饮料近七天的素材详情数据

4. 先测试 `LAST_7_DAYS` 单素材详情，确认网关响应、原始详情文件、规范化详情记录和素材 ID 一致性。
5. 再测试同一素材的 `LAST_30_DAYS`，确认日期参数转换。
6. 再从一个成功列表场景测试 `CUSTOM` 日期详情，先使用已确认合法的日期区间。
7. 最后再测试多个素材、指定品牌列表产生的选择组，以及详情后的视频/高光处理。每个批次落盘后再开始下一个。
8. 详情测试仍需区分：网关 unsuccessful、OSS 文件下载失败、返回格式无法解析、素材 ID 不匹配、规范化失败和高光后处理失败；不要把它们合并成“详情失败”。

## 推荐首个测试输入

建议下一轮先使用自然语言：

> 查询素材 `7671214258320982035` 在食品饮料近七天的素材详情数据

对应预期参数：

```json
{
  "material_id": "7671214258320982035",
  "date_range_type": "LAST_7_DAYS"
}
```

执行前仍应先回显并确认自然语言解析结果。第一条详情测试不需要重新请求列表，也不应直接执行全部 1000 条详情。

## 新对话启动检查

```bash
cd "/Users/shuzida/Desktop/FDE客户/小仙炖/yuntu-configurable-collection"
git status --short
python -m unittest discover -s tests -q
```

建议先检查列表样本：

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path("runs/nl-b-food-beverage-last7-all-ctr-retry-20260824/normalized/list-records.json")
records = json.loads(p.read_text(encoding="utf-8"))
print(len(records))
print(records[0])
PY
```

## 阶段边界

当前元技能仍只负责采集、原始/规范化数据、批次状态和高光资产；商业分析 Prompt、模型洞察和报告生成暂不进入本阶段。第二 RPA 测试应先聚焦素材详情接口和其持久化契约，不要提前扩展到商业分析或报告。
