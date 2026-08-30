# 云图事实包自动接入与运行副本同步设计

## 背景与根因

仓库已经具备 `scripts/fact_packages.py` 和 `build-facts` 命令，但它们是独立的手工入口。`collect`、`retry-failed`、`retry-unresolved` 和 `retry-highlights` 完成后不会自动生成 `facts/`。同时，实际执行使用 `.system/skills/custom/yuntu-meta-skill` 副本，存在源码仓库已更新而运行副本未同步的风险。

因此，2026-08-30 的真实执行虽然成功采集了榜单、详情和高光帧，却没有产生四类事实包。问题属于执行编排和部署同步缺口，不是事实包字段分类算法缺失。

## 目标

1. 每次 `collect` 成功或部分完成后，自动基于该运行目录生成四类事实包。
2. `retry-failed`、`retry-unresolved`、`retry-highlights` 完成后重新生成事实包，确保快照与最新本地事实一致。
3. 保留 `build-facts` 手工重建入口，用于历史运行目录和修复后的离线重建。
4. 明确同步源码仓库与 `.system/skills/custom/yuntu-meta-skill` 运行副本的校验流程。
5. 将“事实包必须存在”纳入技能交付契约和自动化测试。

## 非目标

- 不改变列表、详情、高光帧的 RPA 请求和选择规则。
- 不在事实包中生成商业洞察、主题判断或推荐结论。
- 不自动补采详情或替换失败素材。
- 不创建隔离 worktree；本次执行直接在 `main` 分支进行。

## 设计决策

采用“采集流程末端统一封装”的方式：在 CLI 层定义一个本地 `_build_facts_after_run` 包装步骤，所有会改变运行产物的命令统一调用它；事实包生成失败时不得伪装为完整成功，并通过 CLI 错误路径返回非零状态。核心 `fetch_batch` 保持职责单一，避免把商业分析产物耦合进批处理内部状态机。

运行副本同步采用显式校验而非静默复制：发布/执行前检查 `.system/skills/custom/yuntu-meta-skill/scripts/collector.py` 与当前仓库脚本的版本标识和 `--help` 命令集合；若运行副本不是当前版本，先同步后再执行。同步动作必须记录源路径、目标路径、提交 SHA 和校验结果。

## 数据流

```text
collect / retry-*
  -> 采集或重试更新 normalized/、highlights-manifest.json
  -> build_fact_packages(run_dir)
  -> facts/manifest.json + 四类 facts/*.json
  -> status/交付校验同时检查 facts 完整性
```

`build-facts` 继续直接读取既有运行目录，不调用 RPA、网络或视频处理逻辑。

## 自动接入接口

新增内部函数：

```python
def _build_facts_after_run(output_dir: str | Path) -> dict:
    """Build facts for a changed run and return its manifest."""
```

该函数调用 `build_fact_packages(output_dir)`，只在批次命令完成写入运行产物后调用。成功时 CLI 输出中增加 `facts_manifest_path` 和 `facts_coverage`；失败时抛出 `FactPackageError`，由现有命令错误处理转换为非零退出。

需要接入的分支：

- `collect`：`fetch_batch` 返回后，无论状态为 `success` 或 `partial`，只要运行目录存在规范化榜单，就生成事实包。
- `retry-failed`、`retry-unresolved`、`retry-highlights`：重试函数返回后重新生成事实包。
- `build-facts`：保持现有行为，不递归调用包装函数。

## 完成态与错误处理

- 事实包失败不回滚已完成的采集文件，但命令必须返回非零并明确指出 `facts` 阶段失败。
- 对没有规范化榜单的失败运行，不生成空榜单事实包；保留原采集失败状态。
- 事实包构建器现有的 material ID 冲突、非法 JSON、输入缺失校验继续生效。
- `status` 读取运行目录时若发现采集完成但 `facts/manifest.json` 缺失，应返回 `facts_status: "missing"`，不能把它当作完整交付。

## 运行副本同步契约

同步脚本或执行前检查必须验证：

1. 源仓库为当前 `main` 工作树，且工作树无未提交改动。
2. 目标副本存在且 `collector.py --help` 包含 `build-facts`。
3. 目标副本的 `fact_packages.py` 与源文件 SHA-256 一致。
4. 同步后执行离线 `python <target>/scripts/collector.py build-facts --run-dir <fixture>`，覆盖四类包输出。

本设计不规定具体部署工具；执行文档提供安全的本地同步命令和回滚检查，禁止把凭证或运行数据复制进技能源码目录。

## 验收标准

1. 新建测试证明 `collect` 和三种 retry 命令完成后会调用事实包构建器。
2. 事实包构建失败时命令非零，且测试能看到明确错误。
3. `status` 能区分 `facts_status=complete/missing/invalid`。
4. 对历史运行目录执行 `build-facts` 后四类包覆盖范围与输入事实一致。
5. 源仓库与运行副本同步检查可在无网络环境完成，并能检测版本不一致。
6. 全量测试通过，当前 `main` 工作树保持干净。
