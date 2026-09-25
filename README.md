# embedded-c-boundary-review

[English](README.en.md) | 简体中文

一套针对 **嵌入式 C 代码中「静态工具查不出、常规功能测试测不到、只在回绕点 / 极端输入 / 长跑之后才爆发」** 的 13 类边界隐患的走查方法与工具集。

可作为 **Agent Skill** 使用（WorkBuddy / Claude Code / Codex / Cursor / CodeBuddy），也可只当**命令行静态扫描器 + 回绕窗口计算器**用。

---

## 为什么需要它

编译器告警和 MISRA 检查覆盖的是「当场能被证明的错误」。真正难缠的是另一类：

- **跑数周才失效**：32 位滴答计数回绕、累计器溢出、自定纪元时间耗尽——测试台架上跑十分钟永远发现不了，到客户手上却变成「偶发某个功能失效，重上电就好」。
- **只在异常输入下崩**：下行协议长度字段没做取小校验、有/无符号比较翻转、`<=` 循环 off-by-one。
- **跨产品复用埋雷**：容错窗口常量直接继承上一代产品的数值，没做回绕窗口核算——4 MHz / 32 位下回绕周期约 1074 s，旧产品沿用的 900 s 窗口吃掉 84%，业务里那个 300 s 定时器就再也不会触发。

这类问题的共同点是**代价极高、复现极难、但检查动作高度套路化**。本项目就是把这套检查动作固定下来，让人（和 Agent）每次走查都按同一张单子过一遍。

> 一个示意演算：计数频率 4 MHz、32 位滴答 → 回绕周期 1073.742 s；容错窗口沿用上一代产品的 900 s → 可用窗口只剩 173.742 s，而业务最长定时器是 300 s。表现为调度异常、周期任务停更。`scripts/scan_boundary_risks.py wrap` 就是把这个核算过程变成一条命令。

## 覆盖的 13 类问题

| # | 条目 | 级别 |
|---|---|---|
| 1 | 32 位毫秒 tick 回绕（容错窗口吃掉回绕周期） | P1 |
| 2 | 时间差计算写法错误（`now > last + timeout`、有/无符号混用） | P1 |
| 3 | 「类千年虫」绝对时间耗尽（32 位秒 / 自定纪元 / RTC 位宽不足） | P1 |
| 4 | 非法 / 未同步时间参与业务 | P1 |
| 5 | 定长累计计数溢出（脉冲 / 能量 / 时长累加器） | P1 |
| 6 | 序列号 / 报文序号回绕（"数值更大即更新"） | P1 |
| 7 | 协议长度字段导致缓冲越界 | **P0** |
| 8 | 环形队列满 / 空判错、策略不统一 | P2 |
| 9 | 有符号 / 无符号混用与比较翻转 | **P0** |
| 10 | 数组与拷贝越界（含 off-by-one） | **P0** |
| 11 | 下行配置量程与本地类型装不下 | P2 |
| 12 | 上电 / 复位 / OTA 后初值当合法数据 | P1 |
| 13 | 跨产品复用的底层 / SDK 参数未重新评估 | P1 |

严重度判据：**P0** = 异常输入即可触发内存破坏 / HardFault；**P1** = 长跑后才失效、常规测试测不到（量产偶发投诉主因，**优先级不低于 P0**）；**P2** = 规范缺失、可维护性风险。

## 三种使用场景

| 场景 | 你怎么说 | 产出 |
|---|---|---|
| 代码走查 | "用边界走查检查 `src/` 下的协议解析和定时器代码" | 扫描结果 + 人工确认后的缺陷明细表 + 验证用例 |
| 故障定位 | "跑了一段时间后某个周期任务停更，重上电恢复，按 13 条清单排查" | 按「现象 → 优先怀疑」表定位条目，再回到代码找证据 |
| 设计评审 | "评审这份方案（只有设计文档，没代码）" | 不出缺陷表，改按 13 条提问清单，指出缺哪些计算表与推导依据 |

## 快速开始

**环境要求**：Python 3.9+，**无第三方依赖**（纯标准库）。

### 方式一：作为 Agent Skill（推荐）

把仓库克隆/复制到任一支持 SKILL.md 标准的工具的技能目录下即可，无需改代码：

```bash
git clone https://github.com/clarayu-hub/embedded-c-boundary-review.git
```

| 工具 | 用户级目录 | 项目级目录 |
|---|---|---|
| WorkBuddy | `~/.workbuddy/skills/` | `<repo>/.workbuddy/skills/` |
| Claude Code | `~/.claude/skills/` | `<repo>/.claude/skills/` |
| Codex | `~/.codex/skills/` | `<repo>/.agents/skills/` |
| Cursor | `~/.cursor/skills/` | `<repo>/.cursor/skills/` |
| CodeBuddy | `~/.codebuddy/skills/` | `<repo>/.codebuddy/skills/` |

> 想在多个工具间共用同一份文件，用**目录联接**指向同一个源目录，而不是复制多份：
> ```powershell
> # Windows（无需管理员权限）
> New-Item -ItemType Junction -Path "$HOME\.codex\skills\embedded-c-boundary-review" `
>                            -Target "$HOME\.workbuddy\skills\embedded-c-boundary-review"
> ```
> ```bash
> # macOS / Linux
> ln -s ~/.workbuddy/skills/embedded-c-boundary-review ~/.codex/skills/embedded-c-boundary-review
> ```

装好后，显式调用或直接用自然语言描述任务（各工具调用方式见其文档）。

### 方式二：只用命令行

```bash
# 扫描源码目录，出候选命中 + Markdown 报告
python scripts/scan_boundary_risks.py scan path/to/fw/src --md scan_report.md

# 回绕周期 / 可用窗口核算（第 1、13 条）
python scripts/scan_boundary_risks.py wrap --freq 4000000 --bits 32 --guard 900 --need 300
```

自检一下（本仓库自带刻意植入缺陷的示例）：

```bash
python scripts/scan_boundary_risks.py scan examples
# 扫描文件数: 1   候选命中: 28   (P0=4 P1=21 P2=3)
```

## 命令行参考

### `scan` — 扫描候选命中

```bash
python scripts/scan_boundary_risks.py scan <源码文件或目录...> [选项]
```

| 选项 | 说明 |
|---|---|
| `--md scan_report.md` | 额外输出 Markdown 报告 |
| `--json hits.json` | 额外输出机器可读结果（便于接入 CI） |
| `--rules R1,R7,R10` | 只跑指定规则 |
| `--min-severity P1` | 只看 P1 及以上（P0/P1/P2） |
| `--ext .c,.h` | 扫描的扩展名，默认 `.c .h .cpp .hpp .cc .cxx .ino` |
| `--max-per-rule N` | 控制台每条规则最多打印 N 条（默认 20，报告不受限） |

**脚本只产出候选写法，不做判定。**「两侧类型是否一致」「校验的是本地容量还是对端声称值」这类判断必须读上下文——每个命中都要按 `references/boundary-checklist.md` 对应小节的**检查动作**人工确认后，才能写进报告的缺陷明细。这是刻意设计：宁可让人多确认一次，也不让工具报出假缺陷。

### `wrap` — 回绕周期与可用窗口核算

```bash
python scripts/scan_boundary_risks.py wrap --freq 4000000 --bits 32 --guard 900 --need 300
```

| 参数 | 含义 |
|---|---|
| `--freq` | 滴答计数频率（Hz），如 `1000`（1 ms）、`4000000` |
| `--bits` | 计数变量位宽，如 `16` / `24` / `32` |
| `--guard` | 容错 / 安全窗口（秒），回绕前后预留的不可调度时间 |
| `--need` | 业务最长定时器需求（秒） |

输出示例（对应上文的示意演算）：

```
回绕周期      : 1073.742 秒  = 17.90 分钟
1/10 回绕周期 : 1.79 分钟
容错窗口      : 900.000 秒
可用等待窗口  : 173.742 秒  = 2.90 分钟   （回绕周期 − 容错窗口）
!! 容错窗口占用超过半个回绕周期，风险高 —— 判定 P1 缺陷
!! 需求 300.000 秒 > 可用窗口 173.742 秒 → 调度异常 —— 判定 P1 缺陷
结论: 存在 P1 级风险，需整改
```

判定阈值：`最长定时器 > 回绕周期的 1/10` 或 `容错窗口占用 > 一半回绕周期`，一律标 P1。末尾还会附常用回绕周期速查表。

### `--list-rules` — 看 13 条规则的风险、修复方向、验证方法

```bash
python scripts/scan_boundary_risks.py --list-rules
```

## 目录结构

```
embedded-c-boundary-review/
├── SKILL.md                        # Agent 技能入口：触发场景、四条硬规则、六步工作流、严重度定义
├── README.md / README.en.md        # 中文 / 英文说明
├── CHANGELOG.md                    # 版本变更记录
├── DEVELOPMENT.md                  # 规则维护说明：新增规则流程、正则约定、自检清单
├── agents/openai.yaml              # Codex 侧界面描述（显示名、默认提示词）
├── references/
│   └── boundary-checklist.md       # 13 条完整判定细则 + 现象→优先怀疑对照表 + 评审清单
├── scripts/
│   └── scan_boundary_risks.py      # 候选命中扫描器 + 回绕周期核算器（纯标准库）
├── assets/
│   └── report-template.md          # 走查报告模板
├── examples/                       # 刻意植入缺陷的示例固件 + 预期扫描结果
├── tests/                          # 回归测试（stdlib unittest）
└── .github/                        # CI 配置
```

## 走查流程（Agent 按此执行，人可照此自查）

1. **明确三件事**：走查范围 / 代码走查还是设计评审 / 产品生命周期几年（第 3、5 条需要它算耗尽年份与累计上限）。
2. **跑扫描**拿到候选命中（`scan`）。
3. **逐条人工确认**：对照 checklist 读上下文，给每条命中打标签 `确定缺陷 / 待确认 / 误报`。
4. **核算回绕窗口**（涉及定时器 / 容错参数时必做，用 `wrap`）。
5. **出报告**：按 `assets/report-template.md` —— 摘要 → 明细 → 待确认清单（写明要谁补什么材料）→ 建议验证用例 → 本次未覆盖范围。
6. **给验证方案**：只挑少而关键的几条（拨表测试、异常长度包 fuzzing、加速老化、NVS 损坏 / OTA 首轮行为），不罗列几十条泛泛的测试项。

## 走查结论的硬要求

每条结论必须**四件套齐全**，缺一即不合格：

```
文件:行 + 代码原文 + 为什么是风险（会怎么坏）+ 怎么改 + 怎么验证
```

可疑写法不许直接写成缺陷——宁可标「待确认」，并在报告里写明需要谁补什么材料。

## 设计边界（它不做什么）

- **不替代**编译器告警、MISRA / 静态分析工具、单元测试——本项目补的是它们覆盖不到的那一类问题。
- **不做**命名 / 风格 / 注释审查，只报清单内的问题（用户额外要求时才扩展）。
- **不自动判定**：扫描器输出的是候选，不是缺陷清单。
- 规则基于常见缺陷模式总结，**不保证覆盖全部**边界问题；判定细则可按你自己的实战案例补充，维护方法见 `DEVELOPMENT.md`。

---

本工具用于辅助人工代码走查，输出结果为**候选线索**而非结论，不构成任何形式的保证。使用者需自行对最终判定负责。

© 2026 clarayu-hub
