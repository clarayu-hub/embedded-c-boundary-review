# embedded-c-boundary-review

English | [简体中文](README.md)

A review method and toolset for **13 classes of boundary bugs in embedded C that static analyzers miss, functional tests never reach, and only surface at wraparound points, on hostile input, or after weeks of uptime.**

Usable as an **Agent Skill** (WorkBuddy / Claude Code / Codex / Cursor / CodeBuddy) or purely as a **CLI static scanner + wraparound-window calculator**.

---

## Why this exists

Compiler warnings and MISRA cover the errors you can prove on the spot. The expensive ones are different:

- **They fail after weeks.** A 32-bit tick counter wraps; an accumulator overflows; a custom-epoch counter runs out. A bench test lasting ten minutes will never see it — but the customer sees "a feature stops working every so often, power-cycle fixes it."
- **They crash only on abnormal input.** A protocol length field copied without clamping it to the local buffer, a signed/unsigned comparison that flips, an off-by-one `<=` loop.
- **They are inherited landmines.** A tolerance window constant carried over from the previous product, never re-checked against the wraparound period: at 4 MHz / 32-bit the counter wraps every ~1074 s, the inherited 900 s window eats 84% of it, and the 300 s business timer will never fire again.

All three share the same traits: **high cost, low reproducibility, but highly routine checks.** This project fixes those checks into one list so a human (or an agent) goes through the same routine every time.

> A worked example: 4 MHz, 32-bit counter → wraparound period 1073.742 s. An inherited 900 s tolerance window leaves only 173.742 s of usable window, while the longest business timer needs 300 s. Symptom: scheduling anomalies, a periodic task stops running. `scan_boundary_risks.py wrap` turns exactly this calculation into one command.

## The 13 problem classes

| # | Item | Severity |
|---|---|---|
| 1 | 32-bit millisecond tick wraparound (tolerance window eating the period) | P1 |
| 2 | Wrong time-delta idiom (`now > last + timeout`, signed/unsigned mixing) | P1 |
| 3 | Absolute-time exhaustion — "Y2K-like" (32-bit seconds, custom epoch, narrow RTC) | P1 |
| 4 | Invalid / unsynchronized time feeding business logic | P1 |
| 5 | Fixed-width accumulator overflow (pulse / energy / duration counters) | P1 |
| 6 | Sequence number wraparound ("larger means newer") | P1 |
| 7 | Protocol length field causing buffer overrun | **P0** |
| 8 | Ring buffer full/empty misjudgment, inconsistent policy | P2 |
| 9 | Signed/unsigned mixing and comparison flip | **P0** |
| 10 | Array and copy overruns (including off-by-one) | **P0** |
| 11 | Downlink configuration range vs. local type capacity | P2 |
| 12 | Boot / reset / post-OTA initial values treated as valid data | P1 |
| 13 | Cross-product reuse of low-level / SDK parameters without re-evaluation | P1 |

Severity: **P0** — abnormal input alone triggers memory corruption / HardFault. **P1** — fails only after long uptime, invisible to normal testing; the main source of sporadic field complaints, and **never lower priority than P0**. **P2** — missing convention, maintainability risk.

## Three ways to use it

| Scenario | What you say | Output |
|---|---|---|
| Code review | "Review the protocol parsing and timer code under `src/` against the boundary checklist" | Scan results + human-confirmed defect table + verification cases |
| Field debugging | "Sensor data stops after three weeks; power-cycle recovers. Triage with the 13-item checklist" | Item located via the symptom → suspect table, then evidence in code |
| Design review | "Review this design doc (no code yet)" | No defect table; a 13-item question list pointing out missing calculations and unsupported parameters |

## Quick start

**Requirements**: Python 3.9+, **no third-party dependencies** (standard library only).

### Option 1 — as an Agent Skill

Clone the repo into the skills directory of any tool that follows the SKILL.md standard:

```bash
git clone https://github.com/clarayu-hub/embedded-c-boundary-review.git
```

| Tool | User-level directory | Project-level directory |
|---|---|---|
| WorkBuddy | `~/.workbuddy/skills/` | `<repo>/.workbuddy/skills/` |
| Claude Code | `~/.claude/skills/` | `<repo>/.claude/skills/` |
| Codex | `~/.codex/skills/` | `<repo>/.agents/skills/` |
| Cursor | `~/.cursor/skills/` | `<repo>/.cursor/skills/` |
| CodeBuddy | `~/.codebuddy/skills/` | `<repo>/.codebuddy/skills/` |

> To share one copy across several tools, use a **directory link** instead of duplicating:
> ```bash
> # macOS / Linux
> ln -s ~/.workbuddy/skills/embedded-c-boundary-review ~/.codex/skills/embedded-c-boundary-review
> ```
> ```powershell
> # Windows (no admin rights needed)
> New-Item -ItemType Junction -Path "$HOME\.codex\skills\embedded-c-boundary-review" `
>                            -Target "$HOME\.workbuddy\skills\embedded-c-boundary-review"
> ```

Then invoke it explicitly or just describe the task in natural language.

### Option 2 — CLI only

```bash
# Scan a source tree: candidate hits + Markdown report
python scripts/scan_boundary_risks.py scan path/to/fw/src --md scan_report.md

# Wraparound period / usable window calculation (items 1 and 13)
python scripts/scan_boundary_risks.py wrap --freq 4000000 --bits 32 --guard 900 --need 300
```

Try it on the bundled intentionally-buggy example:

```bash
python scripts/scan_boundary_risks.py scan examples
# scanned files: 1   candidate hits: 28   (P0=4 P1=21 P2=3)
```

## CLI reference

### `scan` — candidate hit scanner

```bash
python scripts/scan_boundary_risks.py scan <files-or-dirs...> [options]
```

| Option | Description |
|---|---|
| `--md scan_report.md` | Also write a Markdown report |
| `--json hits.json` | Also write machine-readable JSON (for CI) |
| `--rules R1,R7,R10` | Run only the listed rules |
| `--min-severity P1` | Only report P1 and above (P0/P1/P2) |
| `--ext .c,.h` | Extensions to scan; default `.c .h .cpp .hpp .cc .cxx .ino` |
| `--max-per-rule N` | Max hits printed per rule in the console (default 20; reports are unlimited) |

**The scanner produces candidates, not verdicts.** Whether a comparison mixes signedness, or whether a length check uses the local capacity or the peer-claimed value, requires reading the surrounding context. Every hit must be confirmed against the *check action* in `references/boundary-checklist.md` before it goes into a defect table. This is deliberate: better one extra human confirmation than a false defect.

### `wrap` — wraparound period and usable window

```bash
python scripts/scan_boundary_risks.py wrap --freq 4000000 --bits 32 --guard 900 --need 300
```

| Argument | Meaning |
|---|---|
| `--freq` | Counter frequency in Hz (e.g. `1000` for 1 ms, `4000000`) |
| `--bits` | Counter width in bits (`16` / `24` / `32`) |
| `--guard` | Tolerance / guard window in seconds reserved around the wrap point |
| `--need` | Longest business timer requirement in seconds |

```
wraparound period : 1073.742 s  = 17.90 min
1/10 of period    : 1.79 min
guard window      : 900.000 s
usable window     : 173.742 s   (= period − guard)
!! guard window exceeds half the period — P1 defect
!! need 300.000 s > usable window 173.742 s -> scheduling failure — P1 defect
verdict: P1 risk present, rework required
```

Thresholds: `longest timer > period / 10`, or `guard window > half the period` → always P1. A quick-reference table of common wraparound periods is printed at the end.

### `--list-rules`

Prints all 13 rules with their risk description, fix direction, and verification method.

## Repository layout

```
embedded-c-boundary-review/
├── SKILL.md                        # Agent entry: triggers, hard rules, 6-step workflow, severity
├── README.md / README.en.md        # Chinese / English docs
├── CHANGELOG.md                    # Version history
├── DEVELOPMENT.md                  # Rule maintenance: how to add a rule, regex conventions, self-checks
├── agents/openai.yaml              # Codex UI metadata (display name, default prompt)
├── references/
│   └── boundary-checklist.md       # Full criteria for all 13 items + symptom → suspect table
├── scripts/
│   └── scan_boundary_risks.py      # Candidate scanner + wraparound calculator (stdlib only)
├── assets/
│   └── report-template.md          # Review report template
├── examples/                       # Intentionally buggy firmware + expected scan output
├── tests/                          # Regression tests (stdlib unittest)
└── .github/                        # CI configuration
```

## Review workflow

1. **Pin down three things**: scope / code review vs. design review / product lifetime in years (items 3 and 5 need it to compute exhaustion dates and accumulator ceilings).
2. **Run the scanner** for candidate hits.
3. **Confirm each hit manually** against the checklist; label it `confirmed defect / to be confirmed / false positive`.
4. **Compute the wraparound window** whenever timers or tolerance constants are involved.
5. **Write the report** per `assets/report-template.md`: summary → details → open questions (who must supply what) → verification cases → what was not covered.
6. **Propose verification**: a few high-value ones (clock-shifting test, malformed-length fuzzing, accelerated aging of counters, corrupted NVS / first boot after OTA) — not a laundry list.

## Rule for every finding

Each finding must carry all four parts, or it does not qualify:

```
file:line + code as written + why it is a risk (how it breaks) + how to fix + how to verify
```

A suspicious pattern must never be promoted to "defect" on the spot — mark it "to be confirmed" and state who needs to supply what evidence.

## Scope and non-goals

- **Not a replacement** for compiler warnings, MISRA / static analysis, or unit tests — it covers what they miss.
- **No naming / style / comment review**; only the 13 listed classes (unless explicitly asked to extend).
- **No automatic verdicts**: scanner output is candidates, not a defect list.
- The rule set is a distillation of common defect patterns and **makes no claim of completeness**; criteria can be extended with your own field cases — see `DEVELOPMENT.md`.

---

This tool assists human code review. Its output is **candidate evidence, not a conclusion**, and comes with no warranty of any kind. Users remain responsible for final judgments.

© 2026 clarayu-hub
