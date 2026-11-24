"""失效分型、敏感性、留出检验与版本对应的核对。"""

import csv
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory
import unittest

from drill_ledger import apply_revisions, build_events, load_registers
from drill_report import full_report
from drill_typing import (
    assign_types,
    discover_types,
    manifestation_trigger_section,
    sensitivity_section,
    stability_section,
    typing_section,
    version_mapping_section,
)

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TYPES = {
    "SEG-N1-late",
    "SEG-N1-relay_reset",
    "SEG-N1-silent",
    "SEG-N2-late",
    "SEG-N2-list_incomplete",
    "SEG-N2-silent",
    "SEG-N3-list_incomplete",
    "SEG-N3-silent",
    "SEG-N4-relay_reset",
    "CO-grid_power-FEED1-N1:silent-N2:silent",
}


class TypingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registers = load_registers(ROOT / "data")
        cls.observations, _ = apply_revisions(cls.registers)
        cls.events = build_events(cls.registers, cls.observations)
        cls.section, cls.types, cls.supports = typing_section(
            cls.registers, cls.events, cls.observations
        )
        cls.assignments = cls.section["事件归属"]

    def test_discovered_types(self):
        self.assertEqual({t.type_id for t in self.types}, EXPECTED_TYPES)
        for ftype in self.types:
            self.assertGreaterEqual(self.supports[ftype.type_id] and len(self.supports[ftype.type_id]), 2)
            self.assertTrue(ftype.basis)  # 每型都给出链路共性依据

    def test_event_can_have_multiple_types(self):
        hits = self.assignments["E020|E020-shared"]
        self.assertIn("SEG-N1-silent", hits)
        self.assertIn("SEG-N2-silent", hits)
        self.assertIn("CO-grid_power-FEED1-N1:silent-N2:silent", hits)

    def test_unclassified_reasons(self):
        unclassified = self.section["未归类"]
        self.assertTrue(unclassified["E007|E007-N1"].startswith("证据不足"))
        self.assertEqual(unclassified["E001|E001-N1"], "无确证失效表现")
        self.assertEqual(
            unclassified["E039|E039-shared"], "仅岗位口径外证据：严格口径下不能归类"
        )
        self.assertEqual(unclassified["E005|E005-shared"], "孤例：表现组合支持不足，未定型")

    def test_sensitivity_missing_never_defaults_to_failure(self):
        report = sensitivity_section(self.registers, self.events, self.types, self.observations)
        pressure = report["SEG-N3-list_incomplete"]["缺失口径压力"]
        self.assertGreater(pressure["支持上界增量"], 0)
        self.assertIn("E007", pressure["相关未知演练"])

    def test_sensitivity_recording_convention(self):
        report = sensitivity_section(self.registers, self.events, self.types, self.observations)
        gained = report["SEG-N1-silent"]["岗位口径压力"]["新增事件"]
        self.assertTrue(any(key.startswith("E031") for key in gained))
        corroborated = report["SEG-N1-silent"]["转抄口径"]["有转抄佐证的事件"]
        self.assertIn("E012|E012-N1", corroborated)

    def test_stability_holdout(self):
        report = stability_section(self.registers, self.events)
        per_type = report["逐型稳定"]
        self.assertFalse(per_type["SEG-N1-relay_reset"]["稳定"])  # 支持集中在 central
        self.assertTrue(per_type["SEG-N1-silent"]["稳定"])
        holdout = report["留档套用"]
        self.assertEqual(holdout["严格岗位口径"]["SEG-N1-silent"], 0)
        self.assertEqual(holdout["接受口径外记录"]["SEG-N1-silent"], 4)
        self.assertEqual(holdout["严格岗位口径"]["SEG-N4-relay_reset"], 5)

    def test_same_manifestation_different_trigger(self):
        report = manifestation_trigger_section(self.registers, self.events)
        silent = report["失声"]
        self.assertTrue(silent["不可互相证明解除"])
        self.assertIn("grid_power", silent["涉及段触发"])
        self.assertIn("roster_stale", silent["涉及段触发"])

    def test_version_mapping(self):
        report = version_mapping_section(self.registers, self.types)
        per_type = report["逐型对应"]
        self.assertEqual(
            per_type["CO-grid_power-FEED1-N1:silent-N2:silent"]["历史对比口径"],
            "不可直接比较：共路基础在版本间变化，频率需按版本分列",
        )
        self.assertEqual(per_type["SEG-N2-late"]["历史对比口径"], "同口径可比")
        self.assertIn("observe", per_type["SEG-N1-silent"]["版本间变化"]["N1"])

    def test_typing_never_reads_rectification_categories(self):
        # 组织者事后写的整改分类不得反填当时输入：改动 checks 不影响分型
        with TemporaryDirectory() as directory:
            data = Path(directory) / "data"
            copytree(ROOT / "data", data)
            file = data / "checks.csv"
            with file.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
                fieldnames = list(rows[0])
            for row in rows:
                row["mode"] = "roster_stale"
            with file.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(rows)
            before = full_report(ROOT / "data")["失效分型"]
            after = full_report(data)["失效分型"]
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
