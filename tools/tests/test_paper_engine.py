"""Offline regression tests. Never instantiate a live connection or use production DBs."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BASELINE = os.environ.get("PAPER_BASELINE_DIR")


def load(name):
    path = Path(BASELINE) / (name + "_baseline.py") if BASELINE else ROOT / "tools" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name + "_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PaperTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v5 = load("paper_v5mech")
        self.trend = load("paper_trendrule")
        self.v5.DB = str(Path(self.tmp.name) / "v5.db")
        self.trend.DB = str(Path(self.tmp.name) / "trend.db")
        self.c5 = self.v5.init_db()
        self.ct = self.trend.init_db()
        self.sym = "ACEUSDT"
        self.hour = 3600000
        self.start = 1700002800000  # hour aligned
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()

    def tearDown(self):
        self.output.__exit__(None, None, None)
        self.c5.close()
        self.ct.close()
        self.tmp.cleanup()

    def v5bars(self, n=223):
        return [(self.start + i*self.hour, 100., 100.5, 99.5, 100., 1.) for i in range(n)]

    def trendbar(self, o=100., h=101., l=99., c=100.):
        t = self.trend
        t.bars[self.sym].extend((self.start+i*60000, 100., 100.1, 99.9, 100., 1.) for i in range(420))
        return (self.start + 420*60000, o, h, l, c, 1.)

    def test_v5_outage_replays_stop_in_intermediate_bar(self):
        m = self.v5
        data = self.v5bars()
        m.enter(self.c5, self.sym, "BUY", 100., 1./1.2, data[219][0])
        m.last_bar[self.sym] = data[219][0]
        m.last_state[self.sym] = "MIXED"
        data[220] = (data[220][0], 100., 100.5, 98., 100., 1.)
        with patch.object(m, "rest_klines", return_value=data):
            m.tick(self.c5, self.sym, data[-1][0]+self.hour)
        self.assertNotIn(self.sym, m.pos, "intermediate stopped position must not survive outage")
        self.assertEqual(self.c5.execute("select status from ai_advice_track").fetchone()[0], "LOSS")

    def test_v5_notional_is_fixed_at_entry(self):
        m = self.v5
        m.enter(self.c5, self.sym, "BUY", 100., 1./1.2, self.start)
        p = m.pos[self.sym]
        m.equity = 100.  # another strategy/symbol lost money after this entry
        m.settle(self.c5, self.sym, p, "WIN", 1., self.start+self.hour)
        self.assertAlmostEqual(m.equity, 102., places=8)

    def test_v5_restart_preserves_cursor_and_regime(self):
        m = self.v5
        data = self.v5bars(221)
        with patch.object(m, "rest_klines", return_value=data):
            m.tick(self.c5, self.sym, data[-1][0]+self.hour)
        cursor, regime = m.last_bar[self.sym], m.last_state[self.sym]
        m.last_bar.clear(); m.last_state.clear(); m.pos.clear()
        m.restore(self.c5)
        self.assertEqual(m.last_bar.get(self.sym), cursor)
        self.assertEqual(m.last_state.get(self.sym), regime)

    def test_v5_duplicate_response_does_not_double_settle(self):
        m = self.v5
        data = self.v5bars(221)
        m.enter(self.c5, self.sym, "BUY", 100., 1./1.2, data[219][0])
        m.last_bar[self.sym] = data[219][0]
        m.last_state[self.sym] = "MIXED"
        data[-1] = (data[-1][0], 100., 100.5, 98., 100., 1.)
        with patch.object(m, "rest_klines", return_value=data):
            m.tick(self.c5, self.sym, data[-1][0]+self.hour)
            equity = m.equity
            m.tick(self.c5, self.sym, data[-1][0]+self.hour)
        self.assertEqual(m.equity, equity)
        self.assertEqual(self.c5.execute("select count(*) from equity_snap").fetchone()[0], 1)

    def test_v5_unfinished_bar_cannot_trigger_stop(self):
        m = self.v5
        data = self.v5bars(222)
        m.enter(self.c5, self.sym, "BUY", 100., 1./1.2, data[220][0])
        m.last_bar[self.sym] = data[220][0]
        m.last_state[self.sym] = "MIXED"
        data[-1] = (data[-1][0], 100., 100.5, 98., 100., 1.)
        with patch.object(m, "rest_klines", return_value=data):
            m.tick(self.c5, self.sym, data[-1][0]+1000)
        self.assertIn(self.sym, m.pos)

    def test_v5_out_of_order_and_duplicate_bars_are_canonical(self):
        m = self.v5
        data = self.v5bars(221)
        shuffled = list(reversed(data)) + [data[0], data[-1]]
        with patch.object(m, "rest_klines", return_value=shuffled):
            m.tick(self.c5, self.sym, data[-1][0]+self.hour)
        self.assertEqual(m.last_bar[self.sym], data[-1][0])

    def test_v5_missing_hour_preserves_cursor(self):
        m = self.v5
        data = self.v5bars(223)
        m.last_bar[self.sym] = data[219][0]
        m.last_state[self.sym] = "MIXED"
        with patch.object(m, "rest_klines", return_value=data[:220]+data[221:]):
            with self.assertRaisesRegex(RuntimeError, "incomplete hour"):
                m.tick(self.c5, self.sym, data[-1][0]+self.hour)
        self.assertEqual(m.last_bar[self.sym], data[219][0])

    def test_v5_timeout_preserves_cursor_and_position(self):
        m = self.v5
        m.enter(self.c5, self.sym, "BUY", 100., 1./1.2, self.start)
        m.last_bar[self.sym] = self.start
        with patch.object(m, "rest_klines", side_effect=TimeoutError("fixture timeout")):
            with self.assertRaises(TimeoutError):
                m.tick(self.c5, self.sym, self.start+self.hour)
        self.assertIn(self.sym, m.pos)
        self.assertEqual(m.last_bar[self.sym], self.start)

    def test_v5_database_failure_rolls_back_memory_and_cursor(self):
        m = self.v5
        data = self.v5bars(221)
        m.enter(self.c5, self.sym, "BUY", 100., 1./1.2, data[219][0])
        self.c5.commit()
        m.last_bar[self.sym] = data[219][0]
        m.last_state[self.sym] = "MIXED"
        data[-1] = (data[-1][0], 100., 100.5, 98., 100., 1.)
        with patch.object(m, "rest_klines", return_value=data), patch.object(m, "save_runtime", side_effect=RuntimeError("disk fault")):
            with self.assertRaisesRegex(RuntimeError, "disk fault"):
                m.tick(self.c5, self.sym, data[-1][0]+self.hour)
        self.assertEqual(m.equity, 200.)
        self.assertIn(self.sym, m.pos)
        self.assertEqual(m.last_bar[self.sym], data[219][0])
        self.assertEqual(self.c5.execute("select status from ai_advice_track").fetchone()[0], "OPEN")

    def test_v5_gap_stop_uses_open_not_unavailable_stop_price(self):
        m = self.v5
        data = self.v5bars(221)
        m.enter(self.c5, self.sym, "BUY", 100., 1./1.2, data[219][0])
        m.last_bar[self.sym] = data[219][0]
        m.last_state[self.sym] = "MIXED"
        data[-1] = (data[-1][0], 95., 96., 94., 95., 1.)
        with patch.object(m, "rest_klines", return_value=data):
            m.tick(self.c5, self.sym, data[-1][0]+self.hour)
        self.assertEqual(self.c5.execute("select result_pct from ai_advice_track").fetchone()[0], -5.)

    def test_short_profit_moves_break_even(self):
        m = self.trend
        bar = self.trendbar(h=100.5, l=95., c=96.)
        m.pos[self.sym] = dict(action="SELL", entry=100., sl=102., tp=94., fill_ms=bar[0], plan_ms=bar[0], risk0=2., breakeven=False)
        m.on_bar(self.ct, self.sym, *bar)
        self.assertTrue(m.pos[self.sym]["breakeven"])
        self.assertEqual(m.pos[self.sym]["sl"], 100.)

    def test_short_loss_does_not_move_break_even(self):
        m = self.trend
        bar = self.trendbar(h=104., l=100.5, c=104.)
        m.pos[self.sym] = dict(action="SELL", entry=100., sl=110., tp=94., fill_ms=bar[0], plan_ms=bar[0], risk0=10., breakeven=False)
        m.on_bar(self.ct, self.sym, *bar)
        self.assertFalse(m.pos[self.sym]["breakeven"])

    def test_buy_limit_above_bar_is_fillable(self):
        m = self.trend
        bar = self.trendbar(o=98., h=99., l=97., c=98.)
        m.pending[self.sym] = dict(action="BUY", entry=100., sl=90., tp=110., plan_ms=bar[0]-60000, risk0=10., breakeven=False)
        m.on_bar(self.ct, self.sym, *bar)
        self.assertIn(self.sym, m.pos)
        self.assertLessEqual(m.pos[self.sym]["entry"], 100., "buy limit cannot fill worse than its limit")

    def test_buy_limit_below_entire_bar_does_not_fill(self):
        m = self.trend
        bar = self.trendbar(o=102., h=103., l=101., c=102.)
        m.pending[self.sym] = dict(action="BUY", entry=100., sl=90., tp=110., plan_ms=bar[0]-60000, risk0=10., breakeven=False)
        m.on_bar(self.ct, self.sym, *bar)
        self.assertNotIn(self.sym, m.pos)

    def test_limit_fill_bar_stop_is_not_ignored(self):
        m = self.trend
        bar = self.trendbar(o=100., h=100.5, l=98., c=100.)
        m.pending[self.sym] = dict(action="BUY", entry=100., sl=99., tp=103., plan_ms=bar[0]-60000, risk0=1., breakeven=False)
        m.on_bar(self.ct, self.sym, *bar)
        self.assertNotIn(self.sym, m.pos)
        self.assertEqual(self.ct.execute("select status from ai_advice_track").fetchone()[0], "LOSS")

    def test_warmup_excludes_unfinished_rest_bar(self):
        m = self.trend
        now_ms = self.start+500*60000+30000
        rows = [(self.start+i*60000, 100., 101., 99., 100., 1.) for i in range(501)]
        with patch.object(m, "SYMBOLS", [self.sym]), patch.object(m, "rest_klines", return_value=rows), patch.object(m.time, "time", return_value=now_ms/1000):
            m.warmup(self.ct)
        self.assertEqual(m.bars[self.sym][-1][0], self.start+499*60000)


if __name__ == "__main__":
    unittest.main()
