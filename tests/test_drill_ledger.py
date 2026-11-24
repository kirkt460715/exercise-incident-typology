"""链路化观测、修订应用与事件构建的核对。"""

from pathlib import Path
import unittest

from drill_ledger import (
    STATE_UNKNOWN,
    apply_revisions,
    build_events,
    load_registers,
    node_statuses,
    version_diffs,
)

ROOT = Path(__file__).resolve().parent.parent


class LedgerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registers = load_registers(ROOT / "data")
        cls.observations, cls.changes = apply_revisions(cls.registers)
        cls.events = build_events(cls.registers, cls.observations)
        cls.by_key = {event.key: event for event in cls.events}

    def test_unknown_is_not_failure(self):
        event = self.by_key["E001|E001-N2"]
        self.assertEqual(event.adverse(), {})
        self.assertEqual(event.unknown_nodes(), ["N2"])
        statuses = node_statuses(self.registers, self.observations)
        self.assertEqual(statuses["E001"]["N2"]["状态"], STATE_UNKNOWN)

    def test_handled_is_confirmed_normal(self):
        event = self.by_key["E001|E001-N1"]
        self.assertEqual(event.normal_nodes(), ["N1"])
        self.assertEqual(event.adverse(), {})

    def test_transcript_only_corroborates(self):
        event = self.by_key["E003|E003-N1"]
        self.assertEqual(len(event.primary), 1)
        self.assertEqual(len(event.transcripts), 1)
        self.assertEqual(event.corroborated_nodes(), ["N1"])
        self.assertEqual(event.adverse(), {"N1": "silent"})

    def test_shared_signal_is_single_event(self):
        event = self.by_key["E020|E020-shared"]
        self.assertTrue(event.shared)
        self.assertEqual(event.adverse(), {"N1": "silent", "N2": "silent"})

    def test_revision_splits_shared_event(self):
        self.assertIn("E039|E039-independent", self.by_key)
        split = self.by_key["E039|E039-independent"]
        self.assertEqual(split.adverse(), {"N2": "late"})
        shared = self.by_key["E039|E039-shared"]
        self.assertNotIn("N2", shared.adverse())
        # 结案日口径下事件尚未拆分
        obs_then, _ = apply_revisions(self.registers, as_of_day=3)
        then = {e.key: e for e in build_events(self.registers, obs_then)}
        self.assertNotIn("E039|E039-independent", then)
        self.assertEqual(then["E039|E039-shared"].adverse(), {"N2": "late"})

    def test_revision_downgrades_observability(self):
        shared = self.by_key["E040|E040-shared"]
        self.assertIn("N2", shared.unknown_nodes())
        self.assertNotIn("N2", shared.adverse())
        obs_then, _ = apply_revisions(self.registers, as_of_day=5)
        then = {e.key: e for e in build_events(self.registers, obs_then)}
        self.assertEqual(then["E040|E040-shared"].adverse(), {"N2": "list_incomplete"})

    def test_offplan_post_not_usable(self):
        record = next(o for o in self.observations if o.record == "E039-N1-0")
        self.assertFalse(record.on_plan_post)  # V2 预案 N1 观察岗位为 station
        self.assertFalse(record.usable())
        self.assertTrue(record.usable(accept_offplan=True))

    def test_version_diffs(self):
        diffs = version_diffs(self.registers)
        self.assertEqual(diffs["N1"]["observe"], {"V1": "dispatcher", "V2": "station"})
        self.assertEqual(diffs["N1"]["path"], {"V1": "FEED1", "V2": "FEED3"})
        self.assertNotIn("N2", diffs)
        self.assertIn("fallback", diffs["N4"])


if __name__ == "__main__":
    unittest.main()
