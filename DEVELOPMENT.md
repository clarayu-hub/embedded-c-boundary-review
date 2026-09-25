# 规则维护说明

本文件供维护者参考：新增/修改判定条目与扫描规则时的约定与自检清单。

## 1. 修改判定细则

`references/boundary-checklist.md` 里每条包含四段：**现象 → 设计阶段动作 → 检查动作 → 验证方法**。修改时请保持这四段结构，并遵循：

- **检查动作要可执行**：写成「打开 X，确认 Y 是不是 Z」，不要写成「注意类型问题」。
- **验证方法要具体**：能落到测试手段（拨表、fuzzing、加速老化……），不要写「充分测试」。
- **四件套缺一不可**：每条结论最终都要能给出 `文件:行 + 代码 + 为什么坏 + 怎么改 + 怎么验证`。

## 2. 扫描器规则（R14 及以后）

规则编号只在「现有 13 条都无法覆盖」时才新增——优先扩充已有规则的 `patterns`。新增流程：

**a. 在 `scripts/scan_boundary_risks.py` 的 `RULES` 列表追加一条**，字段含义：

| 字段 | 说明 |
|---|---|
| `id` | `R<n>`，与 `sop` 序号独立编号，一旦发布不再改动 |
| `sop` | 清单序号（新增时顺延） |
| `title` | 一句话条目名，用于报告分组 |
| `severity` | `P0` / `P1` / `P2`，判据见 SKILL.md |
| `hint` | 为什么这是风险（会怎么坏） |
| `fix` | 修复方向 |
| `verify` | 验证方法 |
| `patterns` | `(标签, 编译后正则)` 列表，命中后按 `label` 输出 |

**b. 正则的硬要求**：

- 只匹配**语法形态**，不要试图匹配语义。判断「两侧类型是否一致」这类工作交给人工走查，脚本命中只是线索。
- 用 `_re()` 包装，保持大小写不敏感等统一选项。
- 避免宽泛标识符碰撞：历史上出现过 `pulse_total` 因含 `ota` 被判成 OTA 分支、`sys_now_ms` 因含 `_no` 被判成序号。新增前请用 `examples/` 与真实项目验证误报率。
- 注释行的处理交给 `strip_code()`，规则本身不用管。

**c. 同步文档**：

- `references/boundary-checklist.md` 增加对应小节（四段结构）
- `SKILL.md` 的速查表更新（序号与级别）
- `README.md` / `README.en.md` 的问题表更新
- `CHANGELOG.md` 记录本次变更

**d. 补测试**：在 `tests/test_scanner.py` 里加一条断言，确保新规则能在示例代码上命中（或确保不误报）。

## 3. 改动后的自检

```bash
# 单元测试全绿
python -m unittest discover -s tests -v

# 示例代码扫描结果与预期一致（examples/README.md 有对照表）
python scripts/scan_boundary_risks.py scan examples

# 脚本仍满足纯标准库、Python 3.9+ 可运行
python scripts/scan_boundary_risks.py --list-rules
```

## 4. 误报 / 漏报的处理

扫描器的定位是「宁多勿漏的候选提示」，所以**误报是可接受的成本，漏报才是真问题**。定位问题时可参考以下信息：

- 最小可复现代码片段（能单独触发命中的那几行，不要贴整个文件）
- 期望结果（漏报时：应该由哪条规则（R?）命中）
- 执行的命令（例如 `--rules R9`）与完整输出

## 5. 其他约定

- 文档与注释以**中文为主**；`README.en.md` 为英文镜像，改动主 README 时请同步英文版。
- 扫描器保持**纯标准库**（不引入第三方依赖）与 Python 3.9 兼容语法，这样任何人 clone 下来即可运行。
- 命中记录中的文件路径统一使用正斜杠，保证跨平台输出可复现（CI 会比对 `examples/expected_scan.md`）。
- 不要提交本地走查产物（`scan_report.md`、`hits.json` 等，已在 `.gitignore` 中）。
