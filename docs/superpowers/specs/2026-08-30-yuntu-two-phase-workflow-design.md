# 云图元技能两阶段工作流设计

## 1. 背景

当前 `pre_input` 已能稳定表达行业、时间、榜单、品牌、人群和高光帧等采集筛选条件。事实包和品牌分类完成后，用户才有足够信息决定商业分析范围与问题，因此采集输入和分析输入不应继续混在一次调用中。

本设计采用方案 A：同一技能保留现有 `pre_input`，将执行拆成“采集与事实准备”和“用户选择后分析”两个阶段，中间通过明确的运行状态衔接。

## 2. 目标

1. 首次调用只处理现有 `pre_input`，完成采集、规范化、事实包和品牌分类。
2. 阶段一完成后输出数据覆盖回执，并暂停自动分析。
3. 用户可在查看回执后选择模块、品牌、素材范围、指标和商业问题。
4. 阶段二生成 `AnalysisSpec`，读取已落盘事实包并执行商业分析。
5. 同一批事实包支持多次、不同角度的分析。

## 3. 非目标

- 不扩展或重定义现有 `pre_input` 的采集字段。
- 不在阶段一自动生成商业洞察。
- 不因阶段二缺少脚本字段而编造脚本结论。
- 不在阶段二重新访问云图或重新执行品牌分类。

## 4. 状态机

```text
collecting → normalizing → fact_packaging → brand_classifying
                                      ↓
                             ready_for_analysis
                                      ↓
                              analysis_running
                                      ↓
                            analysis_completed
```

只有 `ready_for_analysis` 状态允许创建 `AnalysisSpec`。任何采集、事实包或品牌分类门禁失败都进入 `partial`/`failed`，不能启动分析。

## 5. 阶段一协议：CollectionInput

沿用现有 `pre_input` 解析为 `QuerySpec`、`HighlightSpec`。完成后写入 `run-summary.json` 的阶段状态、覆盖计数、事实包 manifest、品牌规则版本和生成时间，并返回：

- 榜单、详情、高光帧数量；
- 四类事实包路径；
- 品牌分类候选和未知品牌数量；
- 脚本字段可用性；
- 阶段状态和下一步提示。

阶段一的输出是可复用的数据资产，不包含商业建议。

## 6. 阶段二协议：AnalysisInput

阶段二支持自然语言或结构化输入，统一解析为：

```json
{
  "run_id": "...",
  "sections": ["material_ranking", "audience", "highlight_frames"],
  "brand_filter": ["小仙炖", "燕之屋"],
  "material_filter": {"rank_range": [1, 100], "material_ids": []},
  "metric_focus": ["exposure", "click", "interaction"],
  "business_question": "比较两个品牌的素材表现和人群差异",
  "report_mode": "standard_with_custom_sections",
  "custom_sections": []
}
```

校验规则：`run_id` 必须匹配已完成运行；`sections` 必须来自事实包；`brand_filter` 必须来自 manifest 候选或“未知品牌”；排名和素材 ID 过滤不能超出事实包；商业问题不能为空。

## 7. 数据流与复用

阶段二只调用事实包读取器和分析编排器：

```text
AnalysisInput → AnalysisSpec → manifest 校验 → 事实包选择
             → PromptPacket → AnalysisResult → Report
```

事实包的 `material_id` 是跨模块关联键。品牌分类快照由阶段一写入各包，阶段二不得重复匹配标题。每条分析结论继续要求 `fact_refs`。

## 8. 交互与错误处理

- 阶段一成功：明确提示“数据已准备完成，请选择分析内容”。
- 阶段一部分完成：展示可用和缺失资产，禁止自动分析。
- 阶段二未指定分析问题：返回可选分析模板，不启动模型分析。
- 阶段二引用不存在的品牌、素材或模块：返回校验错误并列出可用值。
- 脚本包 `source_empty`：进入数据缺口，不用标题或标签替代。

## 9. 兼容与审计

旧运行目录只要存在完整事实包即可进入阶段二；没有阶段状态时由读取器根据 manifest 和 run-summary 推导为只读兼容状态。新运行必须写入阶段状态和协议版本。分析结果保存 `run_id`、`analysis_id`、事实包哈希、提示词版本和生成时间。

## 10. 验收场景

使用 `food-beverage-2026-0810-0820`：首次输入只完成采集/事实准备并停在 `ready_for_analysis`；随后用户选择“素材榜单 + 人群 + TOP4 高光帧”并输入商业问题，系统才生成分析报告。同一运行目录再次选择不同品牌或指标时，不重新采集。

