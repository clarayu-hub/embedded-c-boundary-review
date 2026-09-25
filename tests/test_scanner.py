"""扫描器与核算器的回归测试（纯标准库 unittest，无需第三方依赖）。

运行：
    python -m unittest discover -s tests -v
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "scan_boundary_risks.py"
EXAMPLES = ROOT / "examples"

ALL_RULES = {"R%d" % i for i in range(1, 14)}


def run(*args):
    """以子进程方式调用扫描器，返回 CompletedProcess（UTF-8 文本）。"""
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class TestScan(unittest.TestCase):
    def test_examples_hit_all_13_rules(self):
        """示例文件应覆盖全部 13 条规则，否则说明规则退化了。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "hits.json"
            cp = run("scan", str(EXAMPLES), "--json", str(out))
            self.assertEqual(cp.returncode, 0, cp.stderr)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertGreater(data["files"], 0)
            hit_rules = {h["rule"] for h in data["hits"]}
            self.assertEqual(ALL_RULES - hit_rules, set(),
                             "以下规则未在示例上命中: %s" % sorted(ALL_RULES - hit_rules))

    def test_p0_rules_detected(self):
        """三条 P0 规则（7 长度越界 / 9 类型翻转 / 10 越界）必须命中。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "hits.json"
            run("scan", str(EXAMPLES), "--rules", "R7,R9,R10", "--json", str(out))
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual({h["rule"] for h in data["hits"]}, {"R7", "R9", "R10"})
            self.assertGreaterEqual(data["counts"].get("P0", 0), 3)

    def test_min_severity_filter(self):
        """--min-severity P0 时结果中不得混入 P1/P2。"""
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "hits.json"
            run("scan", str(EXAMPLES), "--min-severity", "P0", "--json", str(out))
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertTrue(data["hits"])
            self.assertEqual({h["severity"] for h in data["hits"]}, {"P0"})

    def test_missing_path_does_not_crash(self):
        """不存在的路径应安静返回 0 命中，而不是抛异常。"""
        cp = run("scan", "/nonexistent_path_for_test_xyz")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("扫描文件数: 0", cp.stdout)

    def test_unknown_rule_returns_2(self):
        """--rules 传了不存在的编号时给出可读提示并以 2 退出。"""
        cp = run("scan", str(EXAMPLES), "--rules", "R99")
        self.assertEqual(cp.returncode, 2)
        self.assertIn("没有匹配的规则", cp.stdout)

    def test_markdown_output_written(self):
        """--md 应生成含标题与统计的 Markdown 报告。"""
        with tempfile.TemporaryDirectory() as td:
            md = Path(td) / "report.md"
            run("scan", str(EXAMPLES), "--md", str(md))
            text = md.read_text(encoding="utf-8")
            self.assertIn("边界风险候选扫描结果", text)
            self.assertIn("候选命中", text)


class TestWrap(unittest.TestCase):
    def test_documented_case(self):
        """4 MHz / 32 位 / 容错窗口 900 s / 需求 300 s 的示意算例必须判 P1。"""
        cp = run("wrap", "--freq", "4000000", "--bits", "32",
                 "--guard", "900", "--need", "300")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = cp.stdout
        self.assertIn("1073.742", out)         # 回绕周期
        self.assertIn("173.742", out)          # 可用窗口 = 1073.742 - 900
        self.assertIn("判定 P1 缺陷", out)
        self.assertIn("存在 P1 级风险", out)

    def test_16bit_1khz_period(self):
        """16 位 @1 kHz 回绕周期 65.536 s。"""
        cp = run("wrap", "--freq", "1000", "--bits", "16")
        self.assertIn("65.536", cp.stdout)

    def test_healthy_config_no_p1(self):
        """32 位 @1 kHz、无容错窗口、需求 1 h：应判为可接受。"""
        cp = run("wrap", "--freq", "1000", "--bits", "32", "--need", "3600")
        self.assertNotIn("存在 P1 级风险", cp.stdout)


class TestListRules(unittest.TestCase):
    def test_lists_all_rules(self):
        cp = run("--list-rules")
        self.assertEqual(cp.returncode, 0, cp.stderr)
        for rid in sorted(ALL_RULES):
            self.assertIn(rid, cp.stdout)


class TestSkillMetadata(unittest.TestCase):
    def test_skill_frontmatter(self):
        """SKILL.md 必须有 name/description，且 name 与目录名一致。"""
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---"), "SKILL.md 应以 YAML frontmatter 开头")
        head = text.split("---")[1]
        self.assertIn("name: embedded-c-boundary-review", head)
        self.assertIn("description:", head)

    def test_no_scan_artifacts_committed(self):
        """仓库内不应残留扫描产物（.gitignore 之外的位置）。"""
        for name in ("scan_report.md", "hits.json"):
            stray = list(ROOT.rglob(name))
            stray = [p for p in stray if ".git" not in p.parts and "examples" not in p.parts]
            self.assertEqual(stray, [], "发现残留产物: %s" % stray)


if __name__ == "__main__":
    unittest.main(verbosity=2)
