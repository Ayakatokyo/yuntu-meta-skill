# 云图元技能入口契约 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align `yuntu-meta-skill/SKILL.md` with its runtime configuration contract by adding a precise entry hint and pre-input template without exposing the internal candidate-pool parameter.

**Architecture:** Keep the implementation documentation-only. Extend the YAML frontmatter with `argument_hint` and `metadata.pre_input`, then make the existing input section explicitly map natural-language fields to `QuerySpec` and `HighlightSpec`; leave scripts and schemas unchanged.

**Tech Stack:** Markdown, YAML frontmatter, Python unittest.

---

### Task 1: Update the skill entry contract

**Files:**
- Modify: `SKILL.md:1-18`

- [ ] **Step 1: Extend the frontmatter with user-facing entry metadata**

Add these fields below the existing `description`, preserving the current skill name and description semantics:

```yaml
argument_hint: 输入行业、时间周期、榜单指标、详情素材数、年龄/性别/八大人群/品牌筛选，以及封面和五项高光指标的截帧策略与帧数；生成并采集 QuerySpec、HighlightSpec 及高光帧资产。
metadata:
  pre_input: 请采集云图行业内容榜单和素材高光帧：行业是 ____（必填）；时间周期是 ____（近7天、近30天或自定义起止日期，默认近7天；自定义日期为闭区间）；榜单指标是 ____（曝光量TOP1000、CTRTOP1000、互动率TOP1000或完播率TOP1000）；详情素材数是 ____（正整数，默认10，最多1000）；年龄是 ____（可选，留空不过滤）；性别是 ____（可选，留空不过滤）；八大人群是 ____（可选，留空不过滤）；品牌范围是 ____（全行业，或指定3至10个品牌）；是否保留封面是 ____（是/否）；点赞指数截帧是 ____（local_peaks或top_values，帧数____）；流失指数截帧是 ____（local_peaks或top_values，帧数____）；点击指数截帧是 ____（local_peaks或top_values，帧数____）；互动指数截帧是 ____（local_peaks或top_values，帧数____）；评论指数截帧是 ____（local_peaks或top_values，帧数____）。
```

- [ ] **Step 2: Rewrite the input section to match the metadata contract**

Replace the current compact input paragraphs with a concise field mapping that states:

```markdown
## 输入

自然语言入口必须从同一句请求解析出两份 JSON：`QuerySpec`（行业、周期、筛选、榜单指标、详情素材数）和 `HighlightSpec`（封面及五项指标的策略/帧数）。文件入口直接读取已保存配置；两种入口使用同一解析器，成功后立即落盘并执行，失败则反馈具体字段错误。

`QuerySpec` 支持行业、近 7 天、近 30 天或自定义日期、年龄、性别、八大人群、品牌范围、四类榜单指标和详情目标素材数。周期默认 `LAST_7_DAYS`；自定义日期是闭区间，起止日期均必填并遵循云图可用日期与跨度限制。年龄、性别、八大人群可留空表示不过滤；品牌范围默认为 `ALL_INDUSTRY`，指定品牌时填写 3 至 10 个品牌。详情目标数默认 10，必须为不超过 1000 的正整数。列表候选池由实现固定为 1000，不作为用户输入字段。

`HighlightSpec` 必须显式包含 `include_cover`，以及点赞、流失、点击、互动、评论五个指数维度；每个维度独立选择 `local_peaks` 或 `top_values` 并指定正整数帧数。未知字段、策略、缺失维度或非法帧数直接拒绝。
```

- [ ] **Step 3: Check the documentation diff**

Run: `git diff --check`

Expected: exit code 0 and no whitespace errors.

### Task 2: Verify the documented contract against the implementation

**Files:**
- Test: `scripts/config_specs.py`
- Test: `tests/test_config_specs.py`

- [ ] **Step 1: Run configuration tests**

Run: `python -m unittest discover -s tests -p 'test_config_specs.py' -v`

Expected: all configuration tests pass with zero failures and zero errors.

- [ ] **Step 2: Run the full test suite**

Run: `python -m unittest discover -s tests -v`

Expected: all repository tests pass with zero failures and zero errors.

- [ ] **Step 3: Check entry-contract invariants**

Run:

```bash
python - <<'PY'
from pathlib import Path

text = Path("SKILL.md").read_text(encoding="utf-8")
frontmatter = text.split("---", 2)[1]
assert "argument_hint:" in frontmatter
assert "metadata:" in frontmatter
assert "pre_input:" in frontmatter
assert "candidate_top_n" not in frontmatter
assert "候选池" not in frontmatter
for metric in ("点赞指数", "流失指数", "点击指数", "互动指数", "评论指数"):
    assert metric in frontmatter
for strategy in ("local_peaks", "top_values"):
    assert strategy in frontmatter
print("entry contract invariants: PASS")
PY
```

Expected: `entry contract invariants: PASS`.

- [ ] **Step 4: Commit the implementation**

Run:

```bash
git add SKILL.md
git commit -m "docs: define yuntu meta skill entry contract"
```
