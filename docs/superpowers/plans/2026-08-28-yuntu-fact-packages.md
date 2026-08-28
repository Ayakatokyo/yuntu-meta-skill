# 云图商业分析事实包 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从任意云图运行目录生成可审计的素材榜单、人群、脚本和高光帧四类事实包，并为当前真实运行落盘。

**Architecture:** 新增纯本地 `scripts/fact_packages.py`，读取既有规范化榜单、详情和高光清单，经过严格校验后原子写入 `facts/` 五个 JSON 文件。`scripts/collector.py` 只增加 `build-facts` 子命令并打印摘要；不触碰 RPA、网络和视频处理链路。

**Tech Stack:** Python 3 标准库、`unittest`、现有 `rpa_io.write_json_atomically`、JSON/sha256。

**Spec:** `docs/superpowers/specs/2026-08-28-yuntu-fact-packages-design.md`

## Global Constraints

- 事实包只保留来源事实，不生成商业洞察、因果解释或推荐结论。
- 榜单事实覆盖规范化列表全部记录，并按 `rank` 升序输出；不以详情数量截断榜单包。
- 人群仅按年龄、性别和平台八大人群来源语义分类；未知标签保留为 `unclassified`。
- 脚本空值与 `source_empty` 必须显式保留，不能静默删除。
- 高光帧保留趋势、high/loss points、清单 reasons、available 和相对路径；不根据图片内容增加解释。
- 输入缺失、非法 JSON 或 material ID 关联冲突必须抛出 `FactPackageError`，且不留下半成品输出。
- 构建器不得改写输入运行目录中的既有文件；输出 JSON 使用 UTF-8、稳定排序和 2 空格缩进。

### Task 1: Fact package builder core

**Files:**
- Create: `scripts/fact_packages.py`
- Test: `tests/test_fact_packages.py`

**Interfaces:**
- Consumes: `normalized/list-records.json`, `normalized/detail-records/*.json`, `raw-csv/list.csv`, `raw-csv/details/*.csv`, `highlights-manifest.json`, optional `run-summary.json`.
- Produces: `build_fact_packages(run_dir, output_dir=None) -> dict` and `FactPackageError`.

- [ ] **Step 1: Write failing tests for package extraction and coverage**

Create a temporary run fixture with two list records, one detail record, one highlight manifest entry, and source CSV placeholders. Assert the builder returns a manifest with four package names, list records sorted by rank, audience dimensions (`crowd_group`, `age`, `gender`), script `source_empty`, and highlight frame availability/path preserved.

```python
def test_build_fact_packages_writes_four_packages_and_classifies_source_facts(self):
    result = build_fact_packages(self.run_dir)
    self.assertEqual(result["coverage"], {
        "ranking_records": 2,
        "detail_records": 1,
        "script_records": 1,
        "highlight_materials": 1,
        "available_highlight_frames": 1,
    })
    ranking = json.loads((self.run_dir / "facts/material-ranking.json").read_text())
    self.assertEqual([row["rank"] for row in ranking["records"]], [1, 2])
    audience = json.loads((self.run_dir / "facts/audience.json").read_text())
    self.assertEqual(
        [(x["tag"], x["dimension"]) for x in audience["records"][0]["observations"]],
        [("精致妈妈", "crowd_group"), ("36-40", "age"), ("女", "gender")],
    )
    script = json.loads((self.run_dir / "facts/script.json").read_text())
    self.assertFalse(script["records"][0]["data_availability"]["script_text"]["available"])
    highlights = json.loads((self.run_dir / "facts/highlight-frames.json").read_text())
    self.assertEqual(highlights["records"][0]["frames"][0]["relative_path"], "highlights/101/01-000s.jpg")
```

- [ ] **Step 2: Run the focused test to verify RED**

Run: `python -m unittest tests.test_fact_packages.FactPackageTests.test_build_fact_packages_writes_four_packages_and_classifies_source_facts -v`

Expected: FAIL with import/function-not-found because `scripts.fact_packages` does not exist.

- [ ] **Step 3: Implement the minimal builder and stable JSON writer**

Implement helpers with these exact responsibilities:

```python
class FactPackageError(ValueError):
    pass

def build_fact_packages(run_dir, *, output_dir=None):
    # validate run root and required normalized list
    # load list/details/highlights, build four payloads
    # write package files to a temporary sibling directory
    # atomically replace output directory only after all writes succeed
    # return manifest payload
```

Use `sha256_file` from `yuntu_run_state` when available or an equivalent local helper. Copy only documented fields into each package. Use `source_paths` relative to run root. For detail files, require the filename material ID and JSON `material_id` to agree; reject duplicate detail IDs. Derive audience dimensions from `AGE_RE`, `男/女`, and `CROWD_GROUPS = {"精致妈妈", "小镇青年", "新锐白领", "资深中产", "小镇中老年", "都市蓝领", "都市银发", "genz", "20-23", ...}` while treating age and gender explicitly before crowd groups; unknown values become `unclassified`.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run: `python -m unittest tests.test_fact_packages -v`

Expected: all builder extraction, classification, and coverage tests PASS.

- [ ] **Step 5: Add failure and immutability tests**

Add tests asserting missing `normalized/list-records.json`, malformed JSON, duplicate/conflicting detail IDs, and invalid highlight JSON raise `FactPackageError`; assert no `facts/` directory remains after each failure. Snapshot SHA-256 of inputs before and after a successful build and assert unchanged.

- [ ] **Step 6: Run the expanded focused tests**

Run: `python -m unittest tests.test_fact_packages -v`

Expected: PASS with zero failures and zero errors.

- [ ] **Step 7: Commit the core builder**

```bash
git add scripts/fact_packages.py tests/test_fact_packages.py
git commit -m "feat: build auditable yuntu fact packages"
```

### Task 2: Add the `build-facts` CLI command

**Files:**
- Modify: `scripts/collector.py`
- Test: `tests/test_collector.py`

**Interfaces:**
- Consumes: `build_fact_packages` and a user-provided `--run-dir`.
- Produces: `python scripts/collector.py build-facts --run-dir <path>`; exit 0 with JSON summary on success and existing CLI error handling on failure.

- [ ] **Step 1: Write the failing CLI dispatch test**

Patch `collector.build_fact_packages` in the test and invoke `collector.main(["build-facts", "--run-dir", str(root)])`; assert it receives the exact path and stdout contains `facts/manifest.json` plus all four package counts.

- [ ] **Step 2: Run the focused CLI test to verify RED**

Run: `python -m unittest tests.test_collector.CollectorTests.test_build_facts_dispatches_to_local_builder -v`

Expected: FAIL because the parser has no `build-facts` command.

- [ ] **Step 3: Implement parser and dispatch**

Add a subparser with required `--run-dir`, import `build_fact_packages` using the existing package/script import pattern, print a compact JSON object containing `manifest_path` and `coverage`, and return a nonzero code through the existing `main` error path when `FactPackageError` is raised.

- [ ] **Step 4: Run CLI and full existing tests**

Run: `python -m unittest tests.test_collector tests.test_fact_packages -v`

Expected: PASS.

- [ ] **Step 5: Commit the CLI**

```bash
git add scripts/collector.py tests/test_collector.py
git commit -m "feat: expose fact package builder command"
```

### Task 3: Materialize and verify the current real run

**Files:**
- Generate: `runs/food-beverage-exposure-top1000-20260828/facts/manifest.json`
- Generate: `runs/food-beverage-exposure-top1000-20260828/facts/material-ranking.json`
- Generate: `runs/food-beverage-exposure-top1000-20260828/facts/audience.json`
- Generate: `runs/food-beverage-exposure-top1000-20260828/facts/script.json`
- Generate: `runs/food-beverage-exposure-top1000-20260828/facts/highlight-frames.json`

**Interfaces:**
- Consumes: the real run directory and the builder/CLI from Tasks 1–2.
- Produces: auditable current-run fact snapshot with coverage ranking 1000, details 2, scripts 2, highlight materials 2, available frames 16.

- [ ] **Step 1: Run the builder against the real run**

Run: `python scripts/collector.py build-facts --run-dir runs/food-beverage-exposure-top1000-20260828`

Expected: exit 0 and printed coverage exactly `1000/2/2/2/16`.

- [ ] **Step 2: Verify package invariants and input immutability**

Run a Python check that loads all five generated JSON files, asserts each package has `schema_version == 1`, all list ranks are 1..1000, detail IDs are exactly the two manifest IDs, script availability reasons are `source_empty`, every available highlight frame points to a nonempty file under the run root, and `run-summary.json`, normalized files, and highlight manifest checksums still match the pre-build values.

- [ ] **Step 3: Run the complete test suite**

Run: `python -m unittest discover -s tests -v`

Expected: all tests PASS with zero failures and zero errors.

- [ ] **Step 4: Commit the real-run fact snapshot**

```bash
git add -f runs/food-beverage-exposure-top1000-20260828/facts
git commit -m "data: materialize food beverage fact packages"
```

