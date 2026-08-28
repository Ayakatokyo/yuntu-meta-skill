# 云图商业分析事实包设计

## 背景

`yuntu-meta-skill` 当前已经能够采集并规范化巨量云图行业内容榜、素材详情和高光帧。下一阶段商业分析需要一个稳定、可回溯、只承载事实的数据层。本设计针对已有运行目录
`runs/food-beverage-exposure-top1000-20260828`，并将实现为可复用的本地事实包构建器，支持未来任意同结构运行目录。

## 目标

1. 从运行目录中的规范化产物和高光清单生成四类事实包：素材榜单、人群、脚本、高光帧。
2. 保留事实来源路径、运行上下文、记录覆盖范围和缺失原因，支持审计与重建。
3. 只做字段整理、拆分和来源语义分类，不生成商业洞察、因果解释或推荐结论。
4. 当前批次生成可直接供后续商业分析读取的 `facts/` 快照。

## 非目标

- 不修改列表、详情或高光帧采集逻辑。
- 不从标题、素材标签或高光画面推断品牌、脚本主题、购买意图或人群画像。
- 不把榜单指标重新计算成新的指标，不覆盖平台原始值。
- 不把详情缺失素材或未生成的帧用排名更低素材补位。

## 数据边界

当前真实运行的客观覆盖范围必须写入事实包清单：

- 榜单：`normalized/list-records.json`，1000 条，原始 `rank` 1 至 1000。
- 详情：`normalized/detail-records/`，2 条，均为全局榜单前 2 条素材。
- 脚本：仅在详情范围内检查；当前 2 条的 `script_text`、`content_formula` 和 `script_segments` 均为空，原因是 `source_empty`。
- 高光帧：`highlights-manifest.json` 中 2 条素材共 16 张 `available=true` JPEG；同时保留趋势、high points、loss points 事实。

未来运行若详情数量、文件结构或可用性不同，清单应按实际扫描结果生成，不能沿用上述固定数字。

## 目录与文件

事实包生成到输入运行目录的 `facts/`：

```text
facts/
  manifest.json
  material-ranking.json
  audience.json
  script.json
  highlight-frames.json
```

所有 JSON 使用 UTF-8、稳定键排序和 2 空格缩进，便于 diff、审计和测试。包文件中的相对路径均相对于运行根目录，而不是相对于 `facts/`。

## 事实包契约

### `manifest.json`

顶层字段：

```json
{
  "schema_version": 1,
  "run_id": "...",
  "run_root": ".",
  "generated_at": "2026-08-28T...Z",
  "classification": {
    "packages": ["material_ranking", "audience", "script", "highlight_frames"],
    "principle": "source_facts_only"
  },
  "coverage": {
    "ranking_records": 1000,
    "detail_records": 2,
    "script_records": 2,
    "highlight_materials": 2,
    "available_highlight_frames": 16
  },
  "packages": {
    "material_ranking": {"path": "facts/material-ranking.json", "record_count": 1000, "source_paths": [...]},
    "audience": {"path": "facts/audience.json", "record_count": 1000, "source_paths": [...]},
    "script": {"path": "facts/script.json", "record_count": 2, "source_paths": [...]},
    "highlight_frames": {"path": "facts/highlight-frames.json", "record_count": 2, "source_paths": [...]}
  },
  "source_artifacts": [{"path": "normalized/list-records.json", "size_bytes": 0, "sha256": "..."}]
}
```

`source_artifacts` 至少登记实际读取的规范化榜单、详情文件、`highlights-manifest.json` 和 `run-summary.json`（存在时），并记录大小与 SHA-256。`generated_at` 只表示生成时间，不参与事实内容判断。

### `material-ranking.json`

顶层为 `{ "schema_version": 1, "records": [...] }`。每条记录保留榜单事实：

```json
{
  "material_id": "...",
  "item_id": "...",
  "rank": 1,
  "title": "...",
  "video_duration": 141,
  "publish_time": "20260817",
  "account_id": "...",
  "material_uri": "...",
  "business_date": "20260828",
  "list_context": {...},
  "selection_group": {...},
  "metrics": {"ctr": 0.0, "cvr": 0.0, "pvr": 0.0, "play_3s_rate": 0.0, "play_5s_rate": 0.0, "play_over_rate": 0.0, "play_duration_avg": 0.0, "show_cnt": 0, "interact_rate": 0.0, "component_click_rate": 0.0},
  "material_tags": ["..."],
  "data_availability": {"metrics": {...}, "material_tags": {...}},
  "source_paths": {"normalized": "normalized/list-records.json", "raw": "raw-csv/list.csv"}
}
```

记录按 `rank` 升序输出。榜单事实不复制 `people_tags`；人群事实通过相同 `material_id` 关联。

### `audience.json`

顶层为 `{ "schema_version": 1, "records": [...] }`。每条榜单素材对应一条记录，保留原始标签并展开为可筛选的来源语义观察：

```json
{
  "material_id": "...",
  "rank": 1,
  "observations": [
    {"tag": "精致妈妈", "dimension": "crowd_group"},
    {"tag": "36-40", "dimension": "age"},
    {"tag": "女", "dimension": "gender"}
  ],
  "raw_people_tags": ["精致妈妈", "36-40", "女"],
  "data_availability": {...},
  "source_paths": {"normalized": "normalized/list-records.json", "raw": "raw-csv/list.csv"}
}
```

仅对已知来源标签做维度标注：年龄区间（如 `24-30`、`60+`）、`男/女` 为 `gender`，其余平台八大人群标签为 `crowd_group`。未知标签保留但标记为 `dimension: "unclassified"`，不得丢弃或猜测。

### `script.json`

顶层为 `{ "schema_version": 1, "records": [...] }`。每条详情素材一条记录：

```json
{
  "material_id": "...",
  "date_range": {...},
  "script_text": "",
  "content_formula": null,
  "script_segments": [],
  "data_availability": {
    "script_text": {"available": false, "missing_reason": "source_empty"},
    "content_formula": {"available": false, "missing_reason": "source_empty"},
    "script_segments": {"available": false, "missing_reason": "source_empty"}
  },
  "source_paths": {"normalized": "normalized/detail-records/<material_id>.json", "raw": "raw-csv/details/<material_id>.csv"}
}
```

脚本包必须保留空值与 `data_availability`，以区分“暂无脚本”与“未扫描”。

### `highlight-frames.json`

顶层为 `{ "schema_version": 1, "records": [...] }`。每条详情素材一条记录，包含详情趋势事实和帧清单：

```json
{
  "material_id": "...",
  "date_range": {...},
  "trend_series": [...],
  "high_points": [...],
  "loss_points": [...],
  "frames": [
    {
      "second": 0,
      "is_cover": true,
      "frame_type": "cover",
      "reasons": [{"type": "cover"}],
      "available": true,
      "relative_path": "highlights/<material_id>/01-000s.jpg",
      "frame_ref": "highlight:<material_id>:cover:0"
    }
  ],
  "data_availability": {...},
  "source_paths": {
    "detail_normalized": "normalized/detail-records/<material_id>.json",
    "detail_raw": "raw-csv/details/<material_id>.csv",
    "manifest": "highlights-manifest.json"
  }
}
```

帧记录原样保留高光清单中的 `reasons`、指标值和排名；不根据画面内容添加解释。文件不存在或 `available=false` 的帧必须保留，以便后续重试和完成态判断。

## 构建器接口与行为

新增纯本地模块 `scripts/fact_packages.py`，提供：

```python
def build_fact_packages(run_dir: str | Path, *, output_dir: str | Path | None = None) -> dict:
    """Read a completed or partial run and write four auditable fact packages."""
```

- `run_dir` 必须是运行根目录；默认输出到 `run_dir/facts`。
- 只读取输入文件，不改写 `normalized/`、`raw-csv/`、高光资产或既有清单。
- 缺少可选详情、高光或脚本字段时生成对应空/不可用事实，并在 `manifest.coverage` 中反映实际覆盖。
- 缺少必需榜单规范化文件、JSON 无法解析或素材 ID 关联冲突时抛出明确的 `FactPackageError`，不生成半成品；写文件采用原子替换。
- 重复执行同一输入应得到除 `generated_at` 外一致的包内容；测试通过固定时间或忽略该字段验证确定性。

## CLI

新增命令：

```bash
python scripts/collector.py build-facts --run-dir runs/example
```

命令打印 `manifest.json` 的路径、四个包的记录数和覆盖摘要；不得调用任何 RPA、网络或视频处理逻辑。

## 测试验收

1. 单元测试覆盖四类包的字段映射、1000 条排序、人群三类维度分类、未知人群标签保留、脚本 `source_empty` 保留、高光帧路径和 `available` 保留。
2. 对真实运行目录执行构建后，清单覆盖为榜单 1000、详情 2、脚本 2、高光素材 2、可用帧 16。
3. 构建器不得改变输入运行目录中既有文件的内容或 checksum。
4. 缺少榜单文件、非法 JSON、详情 material ID 冲突均能失败并给出可定位错误。
5. 全量现有测试与新增事实包测试均通过。

