"""Unit tests for salt.py (pure model, no HA needed)."""
import sys
import unittest

sys.path.insert(0, "/home/dankaz/clack/hacs/clack-ekodar-mqtt/custom_components/clack_ekodar")

from salt import RegenTracker, SaltConfig, SaltModel  # noqa: E402


class TestConfig(unittest.TestCase):
    def test_formula(self):
        c = SaltConfig(bag_kg=25.0, regens_per_bag=10.0)
        self.assertAlmostEqual(c.kg_per_regen(), 2.5)

    def test_explicit_wins(self):
        c = SaltConfig(bag_kg=25.0, regens_per_bag=10.0, kg_per_regen=3.0)
        self.assertAlmostEqual(c.kg_per_regen(), 3.0)

    def test_divide_by_zero_guard(self):
        c = SaltConfig(bag_kg=25.0, regens_per_bag=0.0)
        self.assertIsNone(c.kg_per_regen())
        c2 = SaltConfig(bag_kg=0.0, regens_per_bag=10.0)
        self.assertIsNone(c2.kg_per_regen())

    def test_from_mapping_defaults(self):
        c = SaltConfig.from_mapping({})
        self.assertAlmostEqual(c.bag_kg, 25.0)
        self.assertAlmostEqual(c.kg_per_regen(), 2.5)


class TestModel(unittest.TestCase):
    def setUp(self):
        self.m = SaltModel(SaltConfig(bag_kg=25.0, regens_per_bag=10.0,
                                      tank_kg=60.0, warn_kg=5.0,
                                      warn_regens=2.0))

    def test_initial_unknown(self):
        self.assertIsNone(self.m.level_kg)
        self.assertIsNone(self.m.is_low)  # no false warning
        self.assertIsNone(self.m.percent())
        self.assertFalse(self.m.on_regeneration(ts=1))  # nothing subtracted

    def test_add_bags(self):
        ev = self.m.add_bags(1, ts=100)
        self.assertAlmostEqual(self.m.level_kg, 25.0)
        self.assertEqual(ev["kg"], 25.0)
        self.m.add_bags(2, ts=200)  # 25+50=75 clamped to 60
        self.assertAlmostEqual(self.m.level_kg, 60.0)
        self.assertEqual(len(self.m.events), 2)

    def test_add_invalid(self):
        self.assertEqual(self.m.add_bags(0), {})
        self.assertEqual(self.m.add_bags(-1), {})
        self.assertIsNone(self.m.level_kg)

    def test_regen_subtracts(self):
        self.m.add_bags(1, ts=1)
        for i in range(4):
            self.assertTrue(self.m.on_regeneration(ts=2 + i))
        self.assertAlmostEqual(self.m.level_kg, 15.0)  # 25 - 4*2.5
        self.assertEqual(self.m.regen_remaining(), 6)

    def test_never_negative(self):
        self.m.add_bags(1, ts=1)  # 25 kg
        for i in range(20):
            self.m.on_regeneration(ts=100 + i)
        self.assertEqual(self.m.level_kg, 0.0)
        self.assertTrue(self.m.is_low)

    def test_zero_level_event_flag(self):
        self.m.add_bags(1, ts=1)  # 25
        for i in range(9):
            self.m.on_regeneration(ts=1 + i)  # 25-22.5=2.5
        self.m.on_regeneration(ts=99)  # -> 0.0
        self.assertEqual(self.m.level_kg, 0.0)
        self.assertTrue(self.m.events[-1]["zeroed"])

    def test_low_warning(self):
        self.m.add_bags(1, ts=1)
        self.assertFalse(self.m.is_low)  # 25 kg -> 10 regens left
        for i in range(9):
            self.m.on_regeneration(ts=1 + i)  # left 2.5 -> 1 regen
        self.assertTrue(self.m.is_low)  # < 2 regens AND < warn_kg? 2.5>5 no; regens rule fires

    def test_warning_clears_after_add(self):
        self.m.level_kg = 1.0
        self.assertTrue(self.m.is_low)
        self.m.add_bags(1, ts=5)
        self.assertFalse(self.m.is_low)

    def test_persistence_roundtrip(self):
        self.m.add_bags(2, ts=111)
        self.m.on_regeneration(ts=222)
        state = self.m.to_dict()
        m2 = SaltModel(self.m.config)
        m2.load_state(state)
        self.assertEqual(m2.level_kg, self.m.level_kg)
        self.assertEqual(m2.last_added, self.m.last_added)
        self.assertEqual(len(m2.events), 2)
        self.assertEqual(m2.regens_tracked, 1)

    def test_load_garbage(self):
        self.m.load_state(None)
        self.m.load_state({"level_kg": -5})
        self.m.load_state("not a dict")
        self.assertIsNone(self.m.level_kg)

    def test_no_tank_capacity(self):
        m = SaltModel(SaltConfig(bag_kg=25.0, regens_per_bag=0.0,
                                 kg_per_regen=0.0, tank_kg=0.0))
        m.add_bags(3, ts=1)
        self.assertAlmostEqual(m.level_kg, 75.0)  # no clamp
        self.assertFalse(m.on_regeneration(ts=2))  # kg_per_regen unknown
        self.assertAlmostEqual(m.level_kg, 75.0)


class TestRegenTracker(unittest.TestCase):
    def test_completed_session(self):
        t = RegenTracker()
        T = 1000.0
        self.assertFalse(t.on_message(100, T))
        self.assertFalse(t.on_message(110, T + 30))
        self.assertFalse(t.on_message(110, T + 60))
        # silence on 110, idle frame after the gap -> session ended
        self.assertTrue(t.on_message(100, T + 60 + 130))
        self.assertFalse(t.session_open)

    def test_short_session_ignored(self):
        t = RegenTracker()
        T = 1000.0
        t.on_message(110, T)  # single frame = incomplete capture
        self.assertFalse(t.on_message(100, T + 200))

    def test_still_streaming(self):
        t = RegenTracker()
        T = 1000.0
        t.on_message(110, T)
        t.on_message(110, T + 30)
        self.assertFalse(t.on_message(100, T + 60))  # gap not reached
        self.assertFalse(t.on_message(110, T + 90))  # continues same session
        self.assertEqual(t.msg_count, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
