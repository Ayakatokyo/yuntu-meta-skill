# 云图事实包自动接入与运行副本同步 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让采集和重试命令自动生成四类事实包，并确保实际执行的 `.system/skills/custom` 副本与 `main` 源码同步。

**Architecture:** 在 `collector.py` CLI 末端统一调用现有 `build_fact_packages`，保留 `build-facts` 离线入口。`yuntu_batch.py` 采集状态机不改职责；状态读取增加事实包完整性检查。同步阶段使用 SHA-256 和离线 fixture 验证运行副本。

**Tech Stack:** Python 3 标准库、`unittest`、现有 JSON/原子写入工具、SHA-256。

**Spec:** `docs/superpowers/specs/2026-08-30-yuntu-fact-package-auto-integration-design.md`

## Global Constraints

- 不修改 RPA 请求、详情选择、高光选择和重试语义。
- `collect` 与三种 retry 命令完成后都必须尝试生成事实包。
- 事实包生成失败必须返回非零，并明确报告 facts 阶段错误。
- 不创建 worktree；所有代码和测试直接在 `main` 分支执行。
- 不向 `.system/skills/custom` 写入凭证或运行数据。

### Task 1: 自动接入 collect/retry 流程

**Files:**
- Modify: `scripts/collector.py`
- Test: `tests/test_collector.py`

**Interfaces:**
- Consumes: `build_fact_packages(run_dir)` and existing batch command return statuses.
- Produces: `_build_facts_after_run(output_dir)`, plus CLI output fields `facts_manifest_path` and `facts_coverage`.

- [ ] **Step 1: Write failing tests**

Add tests that patch `collector.fetch_batch`, `retry_failed_batch`, `retry_unresolved_batch`, and `retry_highlights_batch`, patch `build_fact_packages`, then assert each command calls it exactly once with the requested run directory and includes the returned manifest path in stdout.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_collector -v`

Expected: new tests fail because current command branches return immediately after batch operations without building facts.

- [ ] **Step 3: Implement the shared post-run wrapper**

Add `_build_facts_after_run(output_dir)` and call it after each batch/retry function returns. Preserve the batch status code only when facts succeed; allow a nonzero facts error to reach `parser.error`. Keep `build-facts` dispatch unchanged to avoid recursion.

- [ ] **Step 4: Run focused tests and full collector tests**

Run: `python -m unittest tests.test_collector -v`

Expected: all collector tests PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/collector.py tests/test_collector.py
git commit -m "feat: auto-build fact packages after collection"
```

### Task 2: Make status expose fact-package completeness

**Files:**
- Modify: `scripts/yuntu_batch.py`
- Test: `tests/test_yuntu_batch.py`

**Interfaces:**
- Consumes: `facts/manifest.json` and four package files under a run directory.
- Produces: `collection_status(...)['facts_status']` with `complete`, `missing`, or `invalid`.

- [ ] **Step 1: Write failing status tests**

Create tests for a successful run with complete facts (`complete`), no facts directory (`missing`), and malformed manifest (`invalid`).

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_yuntu_batch -v`

Expected: new assertions fail because status currently has no `facts_status` field.

- [ ] **Step 3: Implement read-only facts status validation**

Add a helper that checks manifest JSON, all four package paths, schema version 1, and nonnegative record counts without rewriting files. Return `missing` when no manifest exists and `invalid` for malformed or incomplete artifacts. Do not change existing collection `status` semantics.

- [ ] **Step 4: Run focused tests**

Run: `python -m unittest tests.test_yuntu_batch -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/yuntu_batch.py tests/test_yuntu_batch.py
git commit -m "feat: report fact package completeness in status"
```

### Task 3: Update skill contract and add runtime synchronization check

**Files:**
- Modify: `SKILL.md`
- Create: `scripts/check_runtime_sync.py`
- Test: `tests/test_runtime_sync.py`

**Interfaces:**
- Consumes: source repository path and `.system/skills/custom/yuntu-meta-skill` target path.
- Produces: `check_runtime_sync(source_root, target_root) -> dict` and CLI `python scripts/check_runtime_sync.py --target <path>`.

- [ ] **Step 1: Write failing synchronization tests**

Use temporary source/target directories. Assert matching `scripts/collector.py` and `scripts/fact_packages.py` plus target help output returns `ok=True`; alter one byte and assert `ok=False` with the mismatched file name.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_runtime_sync -v`

Expected: FAIL because the checker module does not exist.

- [ ] **Step 3: Implement deterministic source/target checks**

Compare SHA-256 for the two runtime files, verify target collector help contains `build-facts`, and return structured mismatch reasons. Never copy files automatically and never read credentials.

- [ ] **Step 4: Update `SKILL.md`**

Document that normal collection and retry commands automatically materialize `facts/`, that `build-facts` is for historical/offline runs, and that runtime sync must pass before executing through `.system/skills/custom`.

- [ ] **Step 5: Run focused and full tests**

Run: `python -m unittest tests.test_runtime_sync tests.test_collector tests.test_yuntu_batch -v` and then `python -m unittest discover -s tests -v`.

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add SKILL.md scripts/check_runtime_sync.py tests/test_runtime_sync.py
git commit -m "docs: require runtime sync for automatic fact packages"
```

### Task 4: Synchronize and verify the actual runtime copy

**Files:**
- External target: `.system/skills/custom/yuntu-meta-skill` (only after explicit path validation)
- No generated source files

- [ ] **Step 1: Validate target path**

Confirm the target is exactly `.system/skills/custom/yuntu-meta-skill` under the active execution workspace; refuse to operate on a broader directory.

- [ ] **Step 2: Synchronize only runtime source files**

Copy `SKILL.md`, `scripts/collector.py`, `scripts/fact_packages.py`, and their direct local dependencies using the host’s approved skill-sync mechanism. Do not copy `runs/`, `.system/sessions/`, credentials, or generated reports.

- [ ] **Step 3: Run synchronization checker**

Run: `python scripts/check_runtime_sync.py --target .system/skills/custom/yuntu-meta-skill`

Expected: `ok=true`, matching SHA-256 values, and `build-facts` present in target help.

- [ ] **Step 4: Run an offline fixture through target copy**

Run target `build-facts` against a temporary fixture and assert all four packages plus `manifest.json` are created; no network or RPA calls occur.

- [ ] **Step 5: Verify and document final state**

Run the full test suite, inspect `git status --short`, and record source commit SHA, target file hashes, and fixture coverage in the execution report.

