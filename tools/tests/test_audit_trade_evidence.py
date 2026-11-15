import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('evidence', Path(__file__).resolve().parents[1] / 'audit_trade_evidence.py')
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)


class EvidenceTests(unittest.TestCase):
    def test_partial_entry_and_exit_bars_are_excluded(self):
        bars = [(0, 100, 999, 1, 100), (60000, 100, 103, 98, 102),
                (120000, 102, 999, 1, 99)]
        held, expected, mfe, mae = evidence.excursions(bars, 30000, 150000, 100, True)
        self.assertEqual((len(held), expected, mfe, mae), (1, 1, 3, -2))

    def test_short_excursions_have_correct_sign(self):
        bars = [(60000, 100, 103, 96, 99)]
        _, _, mfe, mae = evidence.excursions(bars, 60000, 120000, 100, False)
        self.assertEqual((mfe, mae), (4, -3))

    def test_missing_bar_is_not_claimed_full_coverage(self):
        held, expected, _, _ = evidence.excursions([(0, 100, 101, 99, 100)], 0, 120000, 100, True)
        self.assertNotEqual(len(held), expected)

    def test_python_utc_and_java_epoch_agree(self):
        self.assertEqual(evidence.epoch('2026-08-19 00:00:00'), evidence.epoch(1787097600000))


if __name__ == '__main__':
    unittest.main()
