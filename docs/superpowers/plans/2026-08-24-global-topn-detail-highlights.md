# 全局 Top N 素材详情与五指标截帧 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从第一 RPA 落盘的 Top1000 列表中，仅对全局原始排名前 N 条请求详情，并要求自然语言解析产物显式配置五项指标的截帧规则。

**Architecture:** 保持列表 RPA 与详情 RPA 的现有边界。QuerySpec 固定保留 1000 条列表记录，`target_top_n` 决定全局详情候选；批处理调度只遍历这个精确候选集。HighlightSpec 在进入批处理前必须显式包含封面设置和五项趋势各自的策略、帧数。

**Tech Stack:** Python 3 标准库、`unittest`、现有 RPA 调度器与 FFmpeg 高光帧处理器。

---

### Task 1: 收紧 QuerySpec 和 HighlightSpec 输入契约

**Files:**
- Modify: `scripts/config_specs.py:145-159`
- Modify: `scripts/config_specs.py:180-198`
- Modify: `tests/test_config_specs.py:29-69`
- Modify: `tests/fixtures/query-spec.json`
- Modify: `tests/fixtures/highlight-spec.json`
- Modify: `tests/test_collector.py:20-60`

- [ ] **Step 1: 写出失败的配置测试**

```python
def test_query_uses_fixed_top_1000_list_capacity(self):
    resolved = resolve_query_spec(query(collection={"target_top_n": 2}))
    self.assertEqual(resolved["collection"], {"target_top_n": 2, "candidate_top_n": 1000})
    with self.assertRaisesRegex(ConfigSpecError, "must be 1000"):
        resolve_query_spec(query(collection={"target_top_n": 2, "candidate_top_n": 4}))

def test_highlight_requires_explicit_cover_and_all_metrics(self):
    with self.assertRaisesRegex(ConfigSpecError, "include_cover"):
        resolve_highlight_spec({"metrics": {}})
    with self.assertRaisesRegex(ConfigSpecError, "five metrics"):
        resolve_highlight_spec({"include_cover": True, "metrics": {"点击指数": {"strategy": "local_peaks", "limit": 1}}})
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `python -m unittest tests.test_config_specs -q`

Expected: FAIL，因为当前解析器允许较小的 `candidate_top_n`，并为缺失的封面和趋势配置填默认值。

- [ ] **Step 3: 实现最小契约校验**

```python
target = _positive(collection.get("target_top_n", 10), "collection.target_top_n")
if target > 1000:
    raise ConfigSpecError("collection.target_top_n cannot exceed 1000")
candidate = _positive(collection.get("candidate_top_n", 1000), "collection.candidate_top_n")
if candidate != 1000:
    raise ConfigSpecError("collection.candidate_top_n must be 1000")
```

```python
if "include_cover" not in payload or not isinstance(payload["include_cover"], bool):
    raise ConfigSpecError("HighlightSpec.include_cover must be boolean")
if set(custom) != set(HIGHLIGHT_METRICS):
    raise ConfigSpecError("HighlightSpec.metrics must explicitly configure all five metrics")
```

Update the two fixtures so `query-spec.json` uses `candidate_top_n: 1000`, and `highlight-spec.json` provides `include_cover` plus all five metric entries. Update collector assertions to expect `candidate_top_n == 1000`.

- [ ] **Step 4: 运行配置和 CLI 透传测试**

Run: `python -m unittest tests.test_config_specs tests.test_collector -q`

Expected: PASS。

- [ ] **Step 5: 提交配置契约改动**

```bash
git add scripts/config_specs.py tests/test_config_specs.py tests/fixtures/query-spec.json tests/fixtures/highlight-spec.json tests/test_collector.py
git commit -m "feat: require explicit global top-n configuration"
```

### Task 2: 将详情选择收敛为列表全局前 N

**Files:**
- Modify: `scripts/yuntu_batch.py:99-177`
- Modify: `scripts/yuntu_batch.py:602-655`
- Modify: `scripts/yuntu_batch.py:773-870`
- Modify: `tests/test_yuntu_batch.py:18-145`

- [ ] **Step 1: 添加全局排序和无补位的失败测试**

Add an invoker that records list and detail calls, then assert the exact IDs requested:

```python
status = batch.fetch_batch(
    shop_id="shop-42", list_params={}, detail_date_params={"date_range_type": "LAST_7_DAYS"},
    target_top_n=2, candidate_top_n=1000, output_dir=root, invoker=invoker,
    highlight_spec=explicit_highlight_spec,
)
self.assertEqual([call[1]["material_id"] for call in invoker.detail_calls], ["101", "202"])
self.assertEqual([item["material_id"] for item in manifest["candidateMaterials"]], ["101", "202"])
self.assertEqual(manifest["selectionGroups"], [])
```

Use list records ordered as rank 1 / group A (`101`), rank 2 / group B (`202`), rank 3 / group A (`303`). Add a second test that makes `101` raise `RuntimeError`; assert `303` is never requested and `101` is present in `rejectedMaterials`.

- [ ] **Step 2: 运行批处理测试，确认失败**

Run: `python -m unittest tests.test_yuntu_batch -q`

Expected: FAIL，因为当前候选按选择组扩展，且调度器会在详情失败后继续消费排名更低的候选。

- [ ] **Step 3: 替换候选和调度逻辑**

Replace `_candidate_materials_from_list` with a helper that sorts normalized records by `rank`, deduplicates `material_id`, preserves selection-group fields for detail validation, and returns at most `target_top_n` records:

```python
def _top_ranked_materials_from_list(records, target_top_n):
    selected, seen = [], set()
    for record in sorted(records, key=lambda item: item["rank"]):
        material_id = record["material_id"]
        if material_id in seen:
            continue
        seen.add(material_id)
        selected.append({
            "rank": record["rank"], "material_id": material_id,
            "selectionGroupId": _selection_group(record)["id"],
            "selectionGroup": _selection_group(record),
        })
        if len(selected) == target_top_n:
            break
    return selected
```

Set `manifest["selectionGroups"] = []`. Simplify `_target_satisfied` to require all `candidateMaterials` to be in `selectedMaterials`, and simplify `_next_detail_wave` to consume only unprocessed entries from that fixed candidate list in rank order. Remove `selected_by_group` from its signature and callers. Keep `selection_group` only in `_detail_request` and `_expected_selection_group`.

- [ ] **Step 4: 运行批处理与恢复回归测试**

Run: `python -m unittest tests.test_yuntu_batch tests.test_yuntu_run_state -q`

Expected: PASS。

- [ ] **Step 5: 提交全局 Top N 调度改动**

```bash
git add scripts/yuntu_batch.py tests/test_yuntu_batch.py tests/test_yuntu_run_state.py
git commit -m "feat: request details for global top-n only"
```

### Task 3: 更新用户入口与连接器说明

**Files:**
- Modify: `SKILL.md:9-34`
- Modify: `references/connectors/juliang-yt/rpa_conn_juliang_yt_industry_content_rankings_list.md:20-31`
- Modify: `references/connectors/juliang-yt/rpa_conn_juliang_yt_industry_content_rankings_detail.md:19-24`

- [ ] **Step 1: 写入固定交互和选择规则**

Document that one natural-language request must specify list filters, global Top N, `include_cover`, and all five metric policies; the agent must convert this to QuerySpec and HighlightSpec, echo it for confirmation, then persist Top1000 and request details for global rank 1 through N only.

Document that Top1000 secondary filtering, boolean logic, re-sorting, manual ID selection, and rank-N failure replacement are excluded from this release.

- [ ] **Step 2: 核对文档与实现字段一致**

Run: `rg -n "candidate_top_n|selection_group|Top N|五项|五个|补位" SKILL.md references scripts/config_specs.py scripts/yuntu_batch.py`

Expected: 文档描述固定 1000 条列表保留容量、全局 Top N 和无补位；代码不再用选择组决定详情数量。

- [ ] **Step 3: 提交入口文档更新**

```bash
git add SKILL.md references/connectors/juliang-yt/rpa_conn_juliang_yt_industry_content_rankings_list.md references/connectors/juliang-yt/rpa_conn_juliang_yt_industry_content_rankings_detail.md
git commit -m "docs: describe global top-n detail workflow"
```

### Task 4: 完整验证

**Files:**
- Verify only

- [ ] **Step 1: 运行完整离线测试套件**

Run: `python -m unittest discover -s tests -q`

Expected: PASS。

- [ ] **Step 2: 校验运行代码可导入**

Run: `python -c "import scripts.collector, scripts.yuntu_batch, scripts.yuntu_highlights"`

Expected: exit code 0。

- [ ] **Step 3: 审查最终变更**

Run: `git status --short && git log --oneline -3`

Expected: 只包含本计划的实现提交；不包含用户已有的 `docs/handoffs/` 未跟踪文件。
