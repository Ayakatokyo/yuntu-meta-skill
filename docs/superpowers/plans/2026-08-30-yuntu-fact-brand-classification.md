# 云图事实包品牌分类 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将本轮指定品牌的可审计标题分类接入四类事实包及商业分析筛选。

**Architecture:** 从 `list_context.brands` 构建运行时品牌规则，单次分类后写入素材榜单并按 `material_id` 传播到其他事实包；分析层只消费分类快照，不重复匹配标题。

**Tech Stack:** Python 3、现有 `scripts/fact_packages.py`、`scripts/analysis_facts.py`、JSON、pytest。

**Spec:** `docs/superpowers/specs/2026-08-30-yuntu-fact-brand-classification-design.md`

## Global Constraints

- 品牌范围严格来自本轮 `pre_input` 的 `list_context.brands`。
- 不使用默认品牌常量扩展当前运行品牌范围。
- Unicode NFKC + `casefold()`；规范名按 `/` 拆分。
- 仅允许显式受控变体；单独“九阳”不识别为“九阳豆浆”。
- 多品牌同时归类，未命中归为“未知品牌”。
- 保留 `matchedBrands` 和命中 token 证据。
- 不根据品类、功效、标签或画面推断品牌。
- 直接在 `main` 执行，不创建隔离 worktree。

---

## 阶段一：品牌规则模块

### Task 1: 抽取运行时品牌分类器

**Files:**
- Create: `scripts/brand_classifier.py`
- Test: `tests/test_brand_classifier.py`

**Interfaces:**
- `build_brand_rules(brands: list[str]) -> tuple[BrandRule, ...]`
- `classify_brand(title: str, *, brands: list[str]) -> dict`

- [ ] 为 `/` 拆分、大小写、Unicode、中英文连续字符串、多品牌、未知品牌和空品牌列表编写失败测试。
- [ ] 为 `九阳豆浆`→`九阳自律豆浆`和单独“九阳”编写受控变体测试。
- [ ] 实现显式规则和 `match_tokens` 审计字段。
- [ ] 运行 `pytest tests/test_brand_classifier.py -q`。

### 阶段一验收

- [ ] 分类器不读取全局默认品牌表。
- [ ] 同一标题命中多个指定品牌时 `matchedBrands` 包含全部品牌。
- [ ] 未命中时 `value == "未知品牌"` 且 `matchedBrands == []`。

## 阶段二：事实包写入与传播

### Task 2: 从运行上下文解析品牌候选

**Files:**
- Modify: `scripts/fact_packages.py`
- Test: `tests/test_fact_packages.py`

**Interfaces:**
- `extract_runtime_brands(records: list[dict]) -> list[str]`
- `_ranking_payload(root, records) -> dict`

- [ ] 测试从 `list_context.brands` 去重并保持输入顺序。
- [ ] 测试品牌来源缺失时生成“未知品牌”分类而不使用默认值。
- [ ] 在榜单记录写入 `brand_classification` 和 `brand_rule_version`。
- [ ] 运行事实包单元测试。

### Task 3: 将分类传播到其他事实包并更新 manifest

**Files:**
- Modify: `scripts/fact_packages.py`
- Test: `tests/test_fact_packages.py`

- [ ] 按 `material_id` 将分类写入 audience、script、highlight-frames 记录。
- [ ] 测试四个包对同一素材返回完全一致的分类快照。
- [ ] manifest 增加候选品牌、规则版本、各分类计数和包哈希。
- [ ] 使用真实运行目录重建 facts，校验候选品牌仅为“小仙炖、燕之屋、五个女博士”。

### 阶段二验收

- [ ] 四类事实包均能按 `material_id` 审计品牌。
- [ ] 未命中素材归入“未知品牌”，没有品类/功效/画面补判。
- [ ] 事实包重新生成保持原始字段不变，仅增加分类字段和 manifest 元数据。

## 阶段三：分析筛选与报告展示

### Task 4: 增加品牌筛选

**Files:**
- Modify: `scripts/analysis_spec.py`
- Modify: `scripts/analysis_facts.py`
- Test: `tests/test_analysis_spec.py`
- Test: `tests/test_analysis_facts.py`

**Interfaces:**
- `AnalysisSpec.filters["brand_filter"] -> tuple[str, ...]`
- `load_selected_facts(run_root: Path, spec: AnalysisSpec) -> dict`

- [ ] 测试拒绝不在 manifest 候选集中的品牌。
- [ ] 测试按单品牌、多品牌和“未知品牌”筛选记录。
- [ ] 测试品牌筛选不改变 rank/material_id 过滤行为。
- [ ] 运行分析准备层完整测试。

### Task 5: 更新 Prompt 和报告边界

**Files:**
- Modify: `scripts/analysis_prompt.py`
- Modify: `scripts/analysis_report.py`
- Modify: `SKILL.md`
- Test: `tests/test_analysis_prompt.py`
- Test: `tests/test_analysis_report.py`

- [ ] Prompt 明确品牌范围来自 manifest，不允许模型扩展品牌。
- [ ] 报告展示 `matchedBrands` 和命中 token，保留未知品牌与代理识别限制。
- [ ] `selection_group` 为空时品牌代理结论仍强制 inference/low confidence。
- [ ] 运行完整测试：`pytest -q`。

### 阶段三验收

- [ ] 用真实运行目录生成按品牌分组的分析输入和报告。
- [ ] 多品牌素材同时出现在多个品牌分组，不再标记为“歧义品牌”。
- [ ] 报告包含品牌候选、规则版本、未知品牌数量和事实引用。

## 完成标准

- [ ] 三阶段测试全部通过。
- [ ] 真实运行目录验证通过且分类可回溯。
- [ ] 旧事实包读取兼容，新事实包包含品牌分类字段。
- [ ] 代码审查通过后再提交实现。

