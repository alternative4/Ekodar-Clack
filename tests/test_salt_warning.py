"""Unit tests for the salt warning layer (t_3dc7971b): status() + messages.

Run from repo root:  python3 -m unittest discover -s tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "custom_components", "clack_ekodar"))

from salt import (SaltConfig, SaltModel, format_status_message)  # noqa: E402


def model(bag=25.0, regens=10.0, per=0.0, tank=60.0, warn_kg=5.0,
          warn_regens=2.0, level=None, regens_done=0):
    m = SaltModel(SaltConfig(bag_kg=bag, regens_per_bag=regens,
                             kg_per_regen=per, tank_kg=tank,
                             warn_kg=warn_kg, warn_regens=warn_regens))
    if level is not None:
        m.level_kg = level
    m.regens_tracked = regens_done
    return m


class TestStatus(unittest.TestCase):
    def test_no_data_when_level_unknown(self):
        st = model().status()
        self.assertEqual(st["kind"], "no_data")
        self.assertEqual(st["bags_recommended"], 1)

    def test_ok_when_level_healthy(self):
        st = model(level=25.0).status()
        self.assertEqual(st["kind"], "ok")
        self.assertEqual(st["bags_recommended"], 0)
        self.assertEqual(st["regen_remaining"], 10)
        self.assertEqual(st["kg_per_regen"], 2.5)

    def test_low_by_regen_threshold(self):
        # 2.5 kg left -> regen_remaining 1 < warn_regens 2 -> low (t_4097c83e §4)
        st = model(level=2.5).status()
        self.assertEqual(st["kind"], "low")
        self.assertEqual(st["regen_remaining"], 1)
        # refill to warn_regens+1 regens (7.5 kg) minus level 2.5 => 5 kg -> 1 bag
        self.assertEqual(st["bags_recommended"], 1)

    def test_low_by_kg_floor(self):
        # warn_regens=0 so only the kg floor can fire; 4 < 5 kg
        st = model(level=4.0, warn_regens=0.0).status()
        self.assertEqual(st["kind"], "low")

    def test_not_low_exactly_at_threshold(self):
        # strict: regen_remaining < N; 5 kg -> exactly 2 -> no false alarm
        st = model(level=5.0).status()
        self.assertEqual(st["regen_remaining"], 2)
        self.assertEqual(st["kind"], "ok")

    def test_empty_bag_zeroed_still_low(self):
        st = model(level=0.0).status()
        self.assertEqual(st["kind"], "low")
        # need to get back to 7.5 kg; clamped by tank 60 -> fine, 1 bag
        self.assertEqual(st["bags_recommended"], 1)

    def test_bags_recommended_multi(self):
        # explicit per=2.5, warn_regens=2 -> target 7.5; level 0, bag 2 kg
        # ceil(7.5/2)=4 bags
        st = model(per=2.5, bag=2.0, level=0.0).status()
        self.assertEqual(st["kind"], "low")
        self.assertEqual(st["bags_recommended"], 4)

    def test_bags_clamped_to_tank(self):
        # tank 60, level 58, low via warn_kg floor (per unknown) — bag 25:
        # need min(7.5-58<0...) -> at least 1 but never more than headroom
        st = model(per=2.5, bag=25.0, level=58.0, warn_kg=0.0,
                   regens=0.0).status()
        # level 58, per 2.5 -> 23 regens left: ok regardless
        self.assertEqual(st["kind"], "ok")

    def test_incomplete_defers_warning(self):
        # level known but kg_per_regen undeterminable (0/0 config) -> deferred
        m = model(level=1.0, regens=0.0, warn_kg=0.0)
        st = m.status()
        self.assertIsNone(st["kg_per_regen"])
        self.assertEqual(st["kind"], "incomplete")
        self.assertIsNone(st["regen_remaining"])
        self.assertEqual(st["bags_recommended"], 1)

    def test_incomplete_when_regen_remaining_none(self):
        # warn_regens configured, level known, bag/regens invalid via explicit
        # zero-bag config: kg_per_regen None -> deferred, not false 'low'
        st = model(bag=0.0, regens=0.0, level=30.0).status()
        self.assertEqual(st["kind"], "incomplete")

    def test_reset_after_add_bags(self):
        m = model(level=2.5)
        self.assertEqual(m.status()["kind"], "low")
        m.add_bags(1, ts=1)
        st = m.status()
        self.assertEqual(st["kind"], "ok")       # 27.5 kg -> 11 regens
        self.assertEqual(st["level_kg"], 27.5)


class TestMessages(unittest.TestCase):
    def test_low_ru_mentions_action(self):
        msg = format_status_message(model(level=2.5).status(), "ru")
        self.assertIn("Мало соли", msg)
        self.assertIn("2.5 кг", msg)
        self.assertIn("«Добавлена соль»", msg)
        self.assertIn("1 мешок", msg)

    def test_low_plural_ru(self):
        st = model(per=2.5, bag=2.0, level=0.0).status()
        self.assertEqual(st["bags_recommended"], 4)
        self.assertIn("4 мешка", format_status_message(st, "ru"))

    def test_low_regen_wording_ru(self):
        msg = format_status_message(model(level=2.5).status(), "ru")
        self.assertIn("хватит на 1 промывку", msg)

    def test_ok_messages(self):
        st = model(level=25.0).status()
        self.assertTrue(format_status_message(st, "ru").startswith("Соль в норме"))
        self.assertIn("25 kg", format_status_message(st, "en"))

    def test_no_data(self):
        st = model().status()
        self.assertIn("Уровень соли неизвестен", format_status_message(st, "ru"))
        self.assertIn("tracking has not started", format_status_message(st, "en"))

    def test_incomplete_deferral_wording(self):
        st = model(level=1.0, regens=0.0, warn_kg=0.0).status()
        ru = format_status_message(st, "ru")
        self.assertIn("неполные", ru)
        self.assertIn("отложен", ru)
        self.assertIn("incomplete", format_status_message(st, "en"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
