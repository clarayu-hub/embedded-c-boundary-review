#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
嵌入式 C 边界风险候选扫描器 + 回绕周期核算器

配套 skill: embedded-c-boundary-review
来源清单:  判定细则见 references/boundary-checklist.md

用法:
    # 1) 候选命中扫描（默认扫 .c/.h/.cpp/.hpp/.cc/.cxx）
    python scan_boundary_risks.py scan <路径...> [--md 报告.md] [--json hits.json]
                                       [--min-severity P0|P1|P2] [--rules R1,R7]
                                       [--ext .c,.h] [--context 0]

    # 2) 回绕周期 / 可用窗口核算（清单第 1、13 条）
    python scan_boundary_risks.py wrap --freq 4000000 --bits 32 --guard 900 --need 300

    # 3) 查看规则表
    python scan_boundary_risks.py --list-rules

注意: 本脚本只产出**可疑写法候选**，不做判定。所有命中都必须按
references/boundary-checklist.md 的「检查/评审动作」读上下文人工确认。
"""

import argparse
import json
import os
import re
import sys

DEFAULT_EXTS = (".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".ino")

# ---------------------------------------------------------------- 标识符模板

# 时间一类标识符: 下划线分词 (sys_time / last_tick / now_ms) 与
# 大小写混合 (sysTime / lastTick / MsTimer) 都能命中。
_TIME = r"\w*(?:time|tick|ticks|uptime|deadline|expire|expired|elapsed|last|prev|now|tmr|timer|timeout)\w*"

# 明显的误伤词，命中即丢弃
NOISE = re.compile(r"^(?:ticket|sticker|attempt|attached|target|attract)$", re.I)


def _re(rx):
    return re.compile(rx, re.I)


# ------------------------------------------------------------------ 规则定义

RULES = [
    {
        "id": "R1",
        "sop": 1,
        "title": "32 位毫秒 tick 回绕",
        "severity": "P1",
        "hint": "时间计数直接比大小，回绕点必然误判；容错窗口类常量可能吃掉整个回绕周期。",
        "fix": "改用无符号/环形比较 (uint32_t)(now - last) >= timeout；容错窗口按 回绕周期 − 容错窗口 = 可用窗口 核算。",
        "verify": "把 tick 拨到回绕点附近，观察超时/周期/抑制窗口；给出回绕周期计算表。",
        "patterns": [
            ("时间量直接比较大小", _re(_TIME + r"\s*(?:>=|<=|>|<)\s*[A-Za-z0-9_(]")),
            ("有符号时间计数定义", _re(r"\b(?:int|int32_t|int16_t|int64_t|long)\s+\w*(?:time|tick|ms|sec)\w*\s*[=;,]")),
            ("容错窗口类宏（数值）", _re(r"#\s*define\s+\w*(?:WINDOW|GUARD|TOLERANCE|MARGIN|SLACK|GRACE)\w*\s+\(?\s*\d+")),
        ],
    },
    {
        "id": "R2",
        "sop": 2,
        "title": "时间差计算写法错误",
        "severity": "P1",
        "hint": "now > last + timeout 会在 now 回绕后立刻误触发；有符号减法/有符号差值同样不安全。",
        "fix": "统一 (uint32_t)(now - last) >= timeout，或使用 elapsed/uptime API；设计文档注明类型与单位。",
        "verify": "拨表测试；走查 now-last 与 now>last+timeout 两种模式逐一核对类型。",
        "patterns": [
            ("now > last + 超时（危险写法）", _re(_TIME + r"\s*(?:>=|<=|>|<)\s*[^;&|]*?\+")),
            ("时间相减（需确认是否转无符号）", _re(_TIME + r"\s*-\s*" + _TIME)),
            ("有符号差值变量", _re(r"\b(?:int|int32_t|int16_t|long)\s+\w*(?:diff|delta|elapsed|remain|gone)\w*\s*[=;,]")),
            ("有符号时间差赋值", _re(r"\b(?:time_t|int32_t|int16_t)\s+\w+\s*=\s*[^;]*" + _TIME + r"\s*-")),
        ],
    },
    {
        "id": "R3",
        "sop": 3,
        "title": "「类千年虫」绝对时间耗尽",
        "severity": "P1",
        "hint": "有符号 32 位 Unix 秒在 2038-01-19 溢出；32 位秒、16 位日计数、自定义纪元、RTC 位宽不足同样会某天突然坏掉。",
        "fix": "按产品生命周期核算每个时间字段的耗尽年份；不足则升级位宽（如 64 位 time_t）或给出业务规避方案。",
        "verify": "给出「时间字段耗尽日期计算表」；确认生命周期内绝对时间与协议时间字段不耗尽。",
        "patterns": [
            ("使用 time_t", _re(r"\btime_t\b")),
            ("32 位秒/纪元字段", _re(r"\b(?:int32_t|uint32_t)\s+\w*(?:sec|secs|second|seconds|epoch|unix|utc)\w*\s*[=;,\[]")),
            ("16 位日计数", _re(r"\b(?:uint16_t|int16_t)\s+\w*(?:day|days|date)\w*\s*[=;,\[]")),
            ("未来年份常量（耗尽点）", _re(r"(?<!\d)(?:203[3-9]|2[1-9]\d{2})(?!\d)")),
            ("自定义纪元基数", _re(r"\b(?:epoch|epoch_?base|EPOCH_?BASE|base_?year)\b\s*[=,)]?\s*\d{4}")),
        ],
    },
    {
        "id": "R4",
        "sop": 4,
        "title": "非法 / 未同步时间参与业务",
        "severity": "P1",
        "hint": "时间为 0、未对时、掉电乱值、明显未来时间若直接用于告警/索引/有效期/上下行判断，会引发连锁异常。",
        "fix": "设计「未同步」标志位与对时前默认状态，所有依赖时间的业务逻辑走明确降级路径。",
        "verify": "上电未对时、对时失败、时间被设为极端值时的业务表现专项测试。",
        "patterns": [
            ("时间取值入口（需查前置同步判断）", _re(r"\b(?:time|localtime|gmtime|mktime|gettimeofday|clock_gettime|rtc_\w*|get_\w*time\w*|hal_rtc\w*|utc_\w*)\s*\(")),
            ("时间同步标志（应有此判断）", _re(r"\w*(?:synced|is_synced|sync_ok|time_set|time_valid|time_ok|ntp_ok|ts_valid)\w*")),
            ("时间戳参与比较", _re(r"\b\w*(?:timestamp|utc|rtc_?time|sys_?time)\w*\s*(?:>=|<=|>|<|==|!=)")),
        ],
    },
    {
        "id": "R5",
        "sop": 5,
        "title": "定长累计计数溢出",
        "severity": "P1",
        "hint": "能量/电量/脉冲/运行时长的 uint16/32 累加器溢出后变小或跳变。",
        "fix": "按生命周期最大累计值选位宽，或明确定义溢出语义（保持/回绕/扩位存储，三选一）。",
        "verify": "给出「最大累计值估算表」；做加速老化/仿真测试验证溢出后表现。",
        "patterns": [
            ("累计器自增赋值", _re(r"\b\w*(?:cnt|count|counter|total|accum|acc|energy|pulse|runtime|usage|volume|flow|wh|kwh)\w*\s*\+=")),
            ("累计器自增", _re(r"\b\w*(?:cnt|count|counter|total|accum|acc|energy|pulse|runtime|usage)\w*\s*\+\+")),
            ("小位宽累计变量", _re(r"\b(?:uint8_t|int8_t|uint16_t|int16_t)\s+\w*(?:cnt|count|total|accum|acc|energy|pulse|runtime|usage)\w*\s*[=;,]")),
        ],
    },
    {
        "id": "R6",
        "sop": 6,
        "title": "序列号 / 报文序号回绕",
        "severity": "P1",
        "hint": "「数值更大即更新」在序号回绕后会把旧包当新包，或丢弃新包。",
        "fix": "协议层定义回绕窗口与环形比较规则（如 (int16_t)(new - old) > 0）。",
        "verify": "构造回绕前后各几个临界序号做专项测试。",
        "patterns": [
            ("序号直接比大小", _re(r"\b\w*(?:seq|sequence|seqno|serial|msg_?id|pkt_?id|pkt_?seq|pkt_?no|frame_?no)\w*\s*(?:>=|<=|>|<)\s*\w")),
            ("新旧包判断语句", _re(r"\bif\s*\([^)]*\b\w*(?:seq|sequence|seqno|serial|msg_?id|pkt_?id|pkt_?seq|pkt_?no|frame_?no)\w*\s*[<>]")),
            ("环形比较（正确写法，需确认窗口）", _re(r"\(\s*(?:int8_t|int16_t|int32_t|uint8_t|uint16_t|uint32_t)\s*\)\s*\([^)]*(?:seq|sn|serial)\w*\s*-")),
        ],
    },
    {
        "id": "R7",
        "sop": 7,
        "title": "协议长度字段导致缓冲越界",
        "severity": "P0",
        "hint": "长度为 0、小于头长、大于接收缓冲时若未先校验再拷贝，可直接 HardFault / 内存破坏。",
        "fix": "所有来自对端的长度字段，先与本地缓冲容量取小并校验合法性，再决定是否拷贝/解析（接口设计强制项）。",
        "verify": "走查校验是否发生在拷贝之前；对超大/超小/零长度异常包做 fuzzing。",
        "patterns": [
            ("拷贝函数（前一行应有长度校验）", _re(r"\b(?:memcpy|memmove|strncpy|strlcpy|strncat|copy_?buf)\s*\(")),
            ("对端长度字段解引用", _re(r"[A-Za-z_]\w*\s*(?:->|\.)\s*(?:len|length|size|plen|dlen|payload_?len|data_?len|msg_?len)\b")),
            ("长度合法性校验（应有此判断）", _re(r"\b\w*(?:len|length|size|plen)\w*\s*(?:>=|<=|==|!=|>|<)\s*(?:sizeof|MAX|BUF|sizeof\()")),
        ],
    },
    {
        "id": "R8",
        "sop": 8,
        "title": "环形队列满 / 空判错",
        "severity": "P2",
        "hint": "满时覆盖未读数据、空读当有效数据，导致事件丢失、状态错乱、偶发逻辑诡异。",
        "fix": "选定单一满/空策略（多留一格法或独立计数法），并明确队列满时的丢弃/覆盖策略写入设计文档。",
        "verify": "走查判满判空是否全局统一；高负载压测验证满时表现。",
        "patterns": [
            ("head/tail 直接相等（无法区分满空）", _re(r"\b(?:head|widx|wr_?idx|write_?idx|in_?idx|tail|ridx|rd_?idx|read_?idx|out_?idx)\s*==\s*\w*(?:head|tail|widx|ridx|wr|rd|write|read|in|out)\w*")),
            ("多留一格法", _re(r"\(\s*\w*(?:head|idx|wr|rd|write|read|in|out)\w*\s*\+\s*1\s*\)\s*%")),
            ("队列满/空标志", _re(r"\b\w*(?:ring|fifo|queue|queue_?buf|rbuf)\w*\s*(?:->|\.)\s*(?:full|empty|is_?full|is_?empty)\b")),
            ("计数值判满", _re(r"\b(?:count|cnt|num|len)\s*(?:==|>=)\s*\w*(?:size|capacity|MAX|DEPTH|LEN)\w*")),
        ],
    },
    {
        "id": "R9",
        "sop": 9,
        "title": "有符号 / 无符号混用与比较翻转",
        "severity": "P0",
        "hint": "长度、差值、剩余空间参与比较时类型不一致，结果可能完全反转（如 unsigned 差值恒真、负数被当成巨大值）。",
        "fix": "接口与变量定义阶段统一有符号/无符号规范；差值比较统一转无符号中间量。",
        "verify": "走查所有长度/差值/剩余空间比较两侧类型；对 0、最大值、最大值-1 做边界测试。",
        "patterns": [
            ("sizeof 赋给有符号变量", _re(r"\b(?:int|int8_t|int16_t|int32_t|long|short)\s+\w+\s*=\s*[^;]*\bsizeof\b")),
            ("无符号下 a-b > 0 恒真", _re(r"if\s*\([^)]*?-[^)]*?(?:>=|>)\s*0(?:u|U)?\s*\)")),
            ("剩余量用无符号相减", _re(r"\b(?:uint8_t|uint16_t|uint32_t|size_t|unsigned)\s+\w*(?:len|size|remain|left|avail|diff|space)\w*\s*=\s*[^;]*-[^;]*;")),
            ("长度/大小与有符号常量比较", _re(r"\b\w*(?:len|size|count|num)\w*\s*(?:>=|<=|>|<)\s*-\s*\d")),
        ],
    },
    {
        "id": "R10",
        "sop": 10,
        "title": "数组与拷贝越界（含 off-by-one）",
        "severity": "P0",
        "hint": "index == capacity、len == 0 未特判、memcpy 长度多 1，都是经典死机源。",
        "fix": "循环与拷贝统一用有效长度约束；空缓冲走单独路径；边界一律用 <，不用 <=。",
        "verify": "走查所有 memcpy/循环边界写法；专项测试 index == capacity、len == 0。",
        "patterns": [
            ("不安全字符串函数", _re(r"\b(?:strcpy|strcat|sprintf|vsprintf|gets|scanf)\s*\(")),
            ("循环用 <= 上界", _re(r"for\s*\([^;]*;[^;]*<=\s*\w*\b(?:len|length|count|size|num|n|capacity|MAX|DEPTH)\w*\s*;")),
            ("用长度做下标", _re(r"\b\w+\[\s*\w*(?:len|length|count|size|num|capacity|depth)\w*\s*\]")),
            ("下标 +1 越界风险", _re(r"\[[^\]\n]*\+\s*1\s*\]")),
            ("拷贝长度 +1", _re(r"\b(?:memcpy|memmove)\s*\([^;]*,[^;]*,[^;]*\+\s*1\s*\)")),
        ],
    },
    {
        "id": "R11",
        "sop": 11,
        "title": "下行配置量程与本地类型装不下",
        "severity": "P2",
        "hint": "云端/App 下发的周期、阈值、时间窗等协议允许但本地 uint8/16 或业务量程装不下。",
        "fix": "接收接口明确本地最大量程并做二次校验/裁剪；不假设「云端不会发出格的值」。",
        "verify": "逐字段核对下行协议定义与本地类型量程；构造超范围配置（周期=0、阈值超大）做测试。",
        "patterns": [
            ("下行值收窄强转", _re(r"\(\s*(?:uint8_t|int8_t|uint16_t|int16_t|unsigned char|char|short)\s*\)\s*\w*(?:cfg|config|param|setting|arg|val|value|payload|rx|down|recv)\w*")),
            ("小位宽接收下行字段", _re(r"\b(?:uint8_t|int8_t|uint16_t|int16_t)\s+\w+\s*=\s*\w*(?:rx|payload|cmd|cfg|config|param|down|recv)\w*\s*(?:\[|\.|->)")),
            ("量程上限宏（需核对协议）", _re(r"\bMAX_\w*(?:PERIOD|THRESHOLD|TIMEOUT|WINDOW|INTERVAL|RETRY)\w*\b")),
        ],
    },
    {
        "id": "R12",
        "sop": 12,
        "title": "上电 / 复位 / OTA 后的初值当合法数据",
        "severity": "P1",
        "hint": "未初始化内存、NVS 损坏、版本升级后旧字段语义变化，被当成合法时间、计数或配置使用。",
        "fix": "关键字段设计默认安全值 + 上电/复位/OTA 后的合法性校验流程。",
        "verify": "走查校验与回默认值逻辑；专项测试 NVS 损坏、首次上电、OTA 后首轮行为。",
        "patterns": [
            ("持久化读取入口（需查合法性校验）", _re(r"\b(?:nvs|nvram|flash|eeprom|fds|persist|storage|kv)\w*_(?:read|load|get|restore|fetch)\w*\s*\(")),
            ("配置载入函数", _re(r"\b(?:read|load|get|restore|fetch)_\w*(?:cfg|config|param|setting|calib|record)\w*\s*\(")),
            ("合法性校验标志（应有 magic/crc/version）", _re(r"\b\w*(?:magic|crc|checksum|chksum|version|ver_?ok|valid)\w*\s*(?:==|!=)")),
            ("OTA / 复位后分支", _re(r"(?:\b|_)(?:ota|upgrade|reboot|reset_?cause|power_?on|first_?boot)\w*")),
        ],
    },
    {
        "id": "R13",
        "sop": 13,
        "title": "跨产品复用的底层 / SDK 参数未重新评估",
        "severity": "P1",
        "hint": "供应商/前项目的容错窗口类参数换主频、换定时器组合后可能完全不适用，且常被当成「调优参数」而在评审中被忽略。",
        "fix": "任何沿用参数必须结合本产品硬件主频与定时器组合重新推导边界并归档选型依据。",
        "verify": "评审要求列出所有「非 SDK 默认值」底层参数清单及推导依据；做多定时器并发/特定时序专项压力测试。",
        "patterns": [
            ("窗口/超时类常量定义", _re(r"#\s*define\s+\w*(?:WINDOW|GUARD|TOLERANCE|MARGIN|SLACK|GRACE|TIMEOUT|RETRY|PERIOD|INTERVAL|THRESHOLD)\w*\s+\(?\s*\d+")),
            ("沿用/供应商来源说明", _re(r"(?:沿用|继承|照搬|供应商|厂家|前项目|前产品|旧版|历史值|legacy|vendor|reference\s+value|推荐值|建议值)"), True),
        ],
    },
]


# ------------------------------------------------------------- 注释/字符串剥离

def strip_code(text):
    """逐行剥离注释与字符串字面量，保留行号与大致列位置。"""
    out = []
    in_block = False
    for lineno, raw in enumerate(text.splitlines(), 1):
        buf = []
        j, n = 0, len(raw)
        while j < n:
            if in_block:
                k = raw.find("*/", j)
                if k == -1:
                    j = n
                else:
                    in_block = False
                    j = k + 2
                continue
            c = raw[j]
            if c == "/" and j + 1 < n and raw[j + 1] == "/":
                break
            if c == "/" and j + 1 < n and raw[j + 1] == "*":
                in_block = True
                j += 2
                continue
            if c in "\"'":
                quote = c
                j += 1
                while j < n:
                    if raw[j] == "\\":
                        j += 2
                        continue
                    if raw[j] == quote:
                        j += 1
                        break
                    j += 1
                buf.append(quote * 2)
                continue
            buf.append(c)
            j += 1
        out.append((lineno, raw, "".join(buf)))
    return out


def _ident_of(match_text):
    m = re.search(r"[A-Za-z_]\w*", match_text)
    return m.group(0) if m else ""


# ------------------------------------------------------------------- 扫描逻辑

def iter_files(paths, exts):
    for p in paths:
        if os.path.isfile(p):
            yield p
            continue
        for root, dirs, files in os.walk(p):
            dirs[:] = [d for d in dirs if d not in
                       {".git", ".svn", "build", "out", "Debug", "Release", "node_modules", "__pycache__"}]
            for f in sorted(files):
                if f.lower().endswith(tuple(e.lower() for e in exts)):
                    yield os.path.join(root, f)


def scan_file(path, rules):
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as exc:
        print("  [skip] %s: %s" % (path, exc), file=sys.stderr)
        return []
    text = data.decode("utf-8", errors="replace")
    if "\ufffd" in text[:2000]:
        text = data.decode("gbk", errors="replace")

    lines = strip_code(text)
    hits = []
    seen = set()
    for lineno, raw, code in lines:
        for rule in rules:
            for pat in rule["patterns"]:
                label, rx = pat[0], pat[1]
                use_raw = len(pat) > 2 and pat[2]
                hay = raw if use_raw else code
                m = rx.search(hay)
                if not m:
                    continue
                ident = _ident_of(m.group(0))
                if ident and NOISE.match(ident):
                    continue
                key = (rule["id"], lineno)
                if key in seen:
                    continue
                seen.add(key)
                hits.append({
                    "rule": rule["id"],
                    "sop": rule["sop"],
                    "title": rule["title"],
                    "severity": rule["severity"],
                    "file": path.replace("\\", "/"),
                    "line": lineno,
                    "label": label,
                    "code": raw.strip()[:200],
                })
    return hits


SEV_ORDER = {"P0": 0, "P1": 1, "P2": 2}


def cmd_scan(args):
    ids = None
    if args.rules:
        ids = {r.strip().upper() for r in args.rules.split(",") if r.strip()}
    rules = [r for r in RULES if ids is None or r["id"] in ids]
    if not rules:
        print("没有匹配的规则，检查 --rules 取值。可用: " + ", ".join(r["id"] for r in RULES))
        return 2

    all_hits = []
    files = list(iter_files(args.paths, args.ext.split(",")))
    for fp in files:
        all_hits.extend(scan_file(fp, rules))

    min_sev = SEV_ORDER[args.min_severity]
    all_hits = [h for h in all_hits if SEV_ORDER[h["severity"]] <= min_sev]
    all_hits.sort(key=lambda h: (SEV_ORDER[h["severity"]], h["sop"], h["file"], h["line"]))

    counts = {}
    for h in all_hits:
        counts[h["severity"]] = counts.get(h["severity"], 0) + 1

    print("=" * 72)
    print("嵌入式 C 边界风险候选扫描")
    print("扫描文件数: %d   候选命中: %d   (P0=%d P1=%d P2=%d)" % (
        len(files), len(all_hits), counts.get("P0", 0), counts.get("P1", 0), counts.get("P2", 0)))
    print("=" * 72)

    by_rule = {}
    for h in all_hits:
        by_rule.setdefault(h["rule"], []).append(h)

    for rule in rules:
        rs = by_rule.get(rule["id"])
        if not rs:
            continue
        print("\n[%s][%s] 条目%d %s  —— %d 处候选" % (
            rule["id"], rule["severity"], rule["sop"], rule["title"], len(rs)))
        for h in rs[: args.max_per_rule]:
            print("   %s:%d  (%s)" % (h["file"], h["line"], h["label"]))
            print("       %s" % h["code"])
        if len(rs) > args.max_per_rule:
            print("   ... 另有 %d 处，见 --md/--json 输出" % (len(rs) - args.max_per_rule))

    print("\n提示: 以上均为**候选写法**，必须按 references/boundary-checklist.md 逐条人工确认，"
          "\n      不得直接当作缺陷写入报告。")

    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"files": len(files), "counts": counts, "hits": all_hits},
                      fh, ensure_ascii=False, indent=2)
        print("JSON 已写入: %s" % args.json)

    if args.md:
        lines = ["# 边界风险候选扫描结果", "",
                 "- 扫描文件数: %d" % len(files),
                 "- 候选命中: %d（P0=%d / P1=%d / P2=%d）" % (
                     len(all_hits), counts.get("P0", 0), counts.get("P1", 0), counts.get("P2", 0)),
                 "",
                 "> 本表为**候选命中**，须逐条人工确认后升级为缺陷；确认结论写入正式走查报告。",
                 ""]
        for rule in rules:
            rs = by_rule.get(rule["id"])
            if not rs:
                continue
            lines.append("## [%s][%s] 条目 %d · %s" % (
                rule["id"], rule["severity"], rule["sop"], rule["title"]))
            lines.append("")
            lines.append("风险: %s" % rule["hint"])
            lines.append("")
            lines.append("| # | 位置 | 命中特征 | 代码 |")
            lines.append("|---|---|---|---|")
            for i, h in enumerate(rs, 1):
                code = h["code"].replace("|", "\\|")
                lines.append("| %d | `%s:%d` | %s | `%s` |" % (
                    i, os.path.basename(h["file"]), h["line"], h["label"], code))
            lines.append("")
            lines.append("修复方向: %s" % rule["fix"])
            lines.append("")
            lines.append("验证: %s" % rule["verify"])
            lines.append("")
        with open(args.md, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(lines))
        print("Markdown 已写入: %s" % args.md)

    return 0


# --------------------------------------------------------------- 回绕周期核算

def humanize(seconds):
    if seconds >= 86400:
        return "%.2f 天" % (seconds / 86400.0)
    if seconds >= 3600:
        return "%.2f 小时" % (seconds / 3600.0)
    if seconds >= 60:
        return "%.2f 分钟" % (seconds / 60.0)
    return "%.3f 秒" % seconds


def cmd_wrap(args):
    freq = float(args.freq)
    if freq <= 0:
        print("--freq 必须大于 0", file=sys.stderr)
        return 2
    capacity = float(2 ** args.bits)
    period = capacity / freq
    freq_s = ("%d" % int(freq)) if float(freq).is_integer() else ("%g" % freq)

    print("=" * 72)
    print("回绕周期核算（清单条目 1 / 13）")
    print("=" * 72)
    print("计数位宽      : %d 位（容量 %d）" % (args.bits, 2 ** args.bits))
    print("计数频率      : %s Hz%s" % (
        freq_s, "（即 1 ms 计数）" if abs(freq - 1000) < 1e-9 else ""))
    print("回绕周期      : %.3f 秒  = %s" % (period, humanize(period)))
    print("1/10 回绕周期 : %s  （超过此跨度的定时器超时判断必须用无符号环形比较）"
          % humanize(period / 10.0))

    bad = False
    if args.guard is not None:
        usable = period - args.guard
        print("-" * 72)
        print("容错窗口      : %.3f 秒" % args.guard)
        print("可用等待窗口  : %.3f 秒  = %s   （回绕周期 − 容错窗口）"
              % (usable, humanize(usable)))
        if usable <= 0:
            print("!! 容错窗口 >= 回绕周期：可用窗口为负，所有超时/周期逻辑必然失效 —— 判定 P1 缺陷")
            bad = True
        elif args.guard > period / 2.0:
            print("!! 容错窗口占用超过半个回绕周期，风险高 —— 判定 P1 缺陷")
            bad = True
    if args.need is not None:
        usable = period - (args.guard or 0.0)
        print("-" * 72)
        print("最长定时器需求: %.3f 秒" % args.need)
        print("需求 / 回绕周期: %.4f  （>0.1 即触发 1/10 规则，必须改环形比较）"
              % (args.need / period))
        if args.need > usable:
            print("!! 需求 %.3f 秒 > 可用窗口 %.3f 秒 → 调度异常（需求超出可用窗口）—— 判定 P1 缺陷"
                  % (args.need, usable))
            bad = True
        else:
            print("OK: 需求 %.3f 秒 <= 可用窗口 %.3f 秒，余量 %.3f 秒" % (
                args.need, usable, usable - args.need))
        if args.need > period / 10.0:
            print("!! 该定时器跨度已超过回绕周期 1/10：其超时判断必须使用无符号环形比较")
            bad = True
    print("=" * 72)
    print("结论: %s" % ("存在 P1 级风险，需整改" if bad else "在当前参数下未发现回绕窗口不足"))

    # 常用换算表
    print("\n常用回绕周期速查:")
    for bits, f, name in ((32, 1000, "32 位 @1kHz(1ms)"), (32, 1e6, "32 位 @1MHz(1us)"),
                          (32, 4e6, "32 位 @4MHz"), (32, 16e6, "32 位 @16MHz"),
                          (16, 1000, "16 位 @1kHz(1ms)"), (24, 1e6, "24 位 @1MHz(1us)")):
        print("   %-20s %s" % (name, humanize((2 ** bits) / f)))
    return 0


def cmd_list_rules(_args):
    print("规则表（severity 为建议初始级别，最终以人工确认为准）\n")
    for r in RULES:
        print("[%s][%s] 条目%-2d %s" % (r["id"], r["severity"], r["sop"], r["title"]))
        print("     风险: %s" % r["hint"])
        print("     修复: %s" % r["fix"])
        print("     验证: %s" % r["verify"])
        print("     模式: %s" % "；".join(p[0] for p in r["patterns"]))
        print()
    return 0


# ---------------------------------------------------------------------- 入口

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="嵌入式 C 边界风险候选扫描器 / 回绕周期核算器（配套 skill: embedded-c-boundary-review）")
    ap.add_argument("--list-rules", action="store_true", help="打印规则表后退出")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("scan", help="扫描源码，输出候选命中")
    s.add_argument("paths", nargs="+", help="源码文件或目录")
    s.add_argument("--md", help="额外输出 Markdown 报告")
    s.add_argument("--json", help="额外输出 JSON 结果")
    s.add_argument("--min-severity", default="P2", choices=["P0", "P1", "P2"],
                   help="只看该级别及以上（默认 P2 全看）")
    s.add_argument("--rules", help="只跑指定规则，如 R1,R7,R10")
    s.add_argument("--ext", default=",".join(DEFAULT_EXTS), help="扫描扩展名，逗号分隔")
    s.add_argument("--max-per-rule", type=int, default=20, help="控制台每规则最多打印条数")
    s.set_defaults(func=cmd_scan)

    w = sub.add_parser("wrap", help="回绕周期与可用窗口核算")
    w.add_argument("--freq", required=True, help="计数频率 Hz，如 4000000")
    w.add_argument("--bits", type=int, required=True, help="计数位宽，如 32")
    w.add_argument("--guard", type=float, default=None, help="容错/安全窗口秒数，如 900")
    w.add_argument("--need", type=float, default=None, help="产品最长定时器需求秒数，如 300")
    w.set_defaults(func=cmd_wrap)

    args = ap.parse_args(argv)
    if args.list_rules or not args.cmd:
        return cmd_list_rules(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
