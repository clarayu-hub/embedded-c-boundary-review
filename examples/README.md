# 示例：刻意植入缺陷的固件

本目录用于两件事：**演示扫描器输出** 与 **回归测试**。

- `risky_firmware.c` — 反面教材，13 类问题各出现至少一次，每处都有 `[R?]` 标记。
  这些写法在真实项目里都会引入缺陷，请勿复制。
- `expected_scan.md` — 对上述文件运行扫描器的真实输出（由 `--md` 生成，可重新生成）。

## 缺陷 → 规则对照表

| 行 | 标记 | 缺陷写法 | 规则 | 级别 |
|---|---|---|---|---|
| 39 | R1 | `if (sys_now_ms > last_report_ms + 300000)` 回绕后永不成立 | R1 32 位 tick 回绕 | P1 |
| 47 | R2 | 有符号变量承接时间相减结果 | R2 时间差计算写法 | P1 |
| 26 / 54 | R3 | 16 位自定纪元日计数，耗尽后无分支 | R3 绝对时间耗尽 | P1 |
| 63 | R4 | `time(NULL)` 取值直接用于有效期判断 | R4 未同步时间参与业务 | P1 |
| 70 | R5 | `uint16_t` 脉冲累加器无溢出语义 | R5 定长累计计数溢出 | P1 |
| 77 | R6 | `if (p->seq > last_seq)` 数值更大即更新 | R6 序号回绕 | P1 |
| 86 | R7 | `memcpy(dst, p->data, p->len)` 长度未校验 | R7 协议长度越界 | **P0** |
| 92 | R8 | `head == tail` 无法区分满空 | R8 环形队列判错 | P2 |
| 106 / 107 | R9 | 无符号相减收窄、`sizeof` 赋给 `int` | R9 有/无符号混用 | **P0** |
| 116 / 117 | R10 | `strcpy` + `for (i = 0; i <= 16; i++)` off-by-one | R10 数组与拷贝越界 | **P0** |
| 125 | R11 | 下行配置直接强转 `uint8_t`，量程未核对 | R11 下行量程 | P2 |
| 135 | R12 | NVS 读回值在 magic 校验前即被使用 | R12 初值当合法数据 | P1 |
| 16 / 17 | R13 | 容错窗口常量直接继承上一代产品数值 | R13 参数复用未评估 | P1 |

## 怎么跑

```bash
# 直接看控制台摘要（默认 P2 及以上）
python scripts/scan_boundary_risks.py scan examples

# 只看 P0/P1
python scripts/scan_boundary_risks.py scan examples --min-severity P1

# 复核单个规则
python scripts/scan_boundary_risks.py scan examples --rules R7,R10

# 重新生成本目录的报告
python scripts/scan_boundary_risks.py scan examples --max-per-rule 6 --md examples/expected_scan.md
```

## 预期结果（当前版本）

```
扫描文件数: 1   候选命中: 28   (P0=4 P1=21 P2=3)
```

> 命中数会随规则调整而变化——**候选数是工具的自检线，不是质量指标**。
> 真正的产出是人工确认后的缺陷明细，命中里包含刻意的近似与待确认项。
