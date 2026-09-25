# Changelog

本项目遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与 [语义化版本](https://semver.org/lang/zh-CN/)。

## [1.0.0] - 2026-09-28

首个版本。

### Added

- `SKILL.md` — Agent 技能入口：触发场景、四条硬规则、六步走查工作流、严重度定义、13 条速查表。
- `references/boundary-checklist.md` — 13 条完整判定细则：现象 → 设计阶段动作 → 检查动作 → 验证方法，另附「现象 → 优先怀疑」对照表与评审现场清单。
- `scripts/scan_boundary_risks.py` — 候选命中扫描器（R1~R13）+ 回绕周期/可用窗口核算器，纯标准库，Python 3.9+。
- `assets/report-template.md` — 走查报告模板，含严重度统计、缺陷明细、待确认清单、建议验证用例。
- `examples/` — 刻意植入 13 类缺陷的示例固件与预期扫描结果，用于自检和演示。
- `tests/` — 扫描器与核算器的回归测试（stdlib `unittest`）。
- `agents/openai.yaml` — Codex 侧界面描述（显示名、默认提示词）。
- 支持 WorkBuddy / Claude Code / Codex / Cursor / CodeBuddy 等遵循 SKILL.md 标准的 Agent 工具。
