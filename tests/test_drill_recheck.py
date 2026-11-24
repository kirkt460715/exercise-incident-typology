"""整改复验核对与逐轮补材料的核对。"""

import csv
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory
import unittest

from drill_ledger import apply_revisions, build_events, load_registers
from drill_recheck import recheck_section
from drill_report import full_report
from drill_typing import discover_types

ROOT = Path(__file__).resolve().parent.parent


class RecheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registers = load_registers(ROOT / "data")
        observations, _ = apply_revisions(cls.registers)
        events = build_events(cls.registers, observations)
        dev_ids = {
            eid for eid, ex in cls.registers.exercises.items() if ex.fold == "development"
        }
        cls.types, _ = discover_types(cls.registers, events, dev_ids)
        cls.results = recheck_section(cls.registers, cls.types)

    def test_c1_must_be_reapproved(self):
        result = self.results["C1"]
        self.assertEqual(result["结论"], "需重新核准并另验")
        defects = "\n".join(result["缺陷"])
        self.assertIn("failed_observer", defects)
        self.assertIn("station", defects)  # 现场岗位不含预案观察岗位
        self.assertIn("早于复验", defects)
        self.assertIn("后续资料改写", defects)
        self.assertEqual(result["触发条件核对"], "部分")  # 原演练为混合降级

    def test_c1_explanation_trace_and_split(self):
        result = self.results["C1"]
        then = {e["事件"]: e for e in result["曾采用解释"]}
        self.assertEqual(then["E039|E039-shared"]["确证失效"], {"N2": "late"})
        self.assertIn("E039|E039-independent", result["解释变化"])
        now = {e["事件"]: e for e in result["当前解释"]}
        self.assertEqual(now["E039|E039-independent"]["确证失效"], {"N2": "late"})

    def test_c2_target_rewritten_by_later_evidence(self):
        result = self.results["C2"]
        self.assertEqual(result["结论"], "需另验或补正")
        self.assertTrue(any("后续资料改写" in d for d in result["缺陷"]))
        self.assertIn(["T1"], [result["影响面"]["列入但不在影响面"]])

    def test_c3_closeable_with_scope(self):
        result = self.results["C3"]
        self.assertEqual(result["结论"], "可结案")
        self.assertEqual(result["覆盖范围"]["村"], ["T3"])
        exposed = {e["节点"] for e in result["未解除暴露"]}
        self.assertIn("N2", exposed)  # 同场迟滞不在本次结案范围

    def test_c4_side_effect_on_shared_relay(self):
        result = self.results["C4"]
        self.assertEqual(result["结论"], "可结案")
        self.assertEqual(result["影响面"]["未列入而受影响"], ["T1"])
        self.assertTrue(any("共用转发点" in n for n in result["提示"]))

    def test_unknown_never_defaulted_to_failure(self):
        self.assertEqual(self.results["C1"]["未知不默认失败"], ["N3"])

    def test_unresolved_exposures_tracked(self):
        exposed = {e["节点"] for e in self.results["C1"]["未解除暴露"]}
        self.assertIn("N2", exposed)
        self.assertIn("N4", exposed)


class IncrementTests(unittest.TestCase):
    def test_new_round_can_be_appended(self):
        with TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            copytree(ROOT / "data", data)
            with (data / "exercises.csv").open("a", encoding="utf-8", newline="") as stream:
                stream.write("E043,V2,central,grid_power,holdout\n")
            with (data / "observations.csv").open("a", encoding="utf-8", newline="") as stream:
                # V2 预案 N1 观察岗位为 station，此条为岗位内记录
                stream.write("E043-N1-0,E043,N1,station,known,silent,E043-N1\n")
            report = full_report(data)
            self.assertIn("E043", report["失效分型"]["逐演练特征"])
            holdout = report["留出检验"]["留档套用"]
            self.assertEqual(holdout["严格岗位口径"]["SEG-N1-silent"], 1)
            # 既有结论不因补材料而丢失
            self.assertEqual(report["整改复验"]["C1"]["结论"], "需重新核准并另验")


if __name__ == "__main__":
    unittest.main()
