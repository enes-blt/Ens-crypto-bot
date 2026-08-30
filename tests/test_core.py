import math
import unittest

from crypto_trend.backtest import Config, resample_4h, run
from crypto_trend.indicators import atr, donchian_previous, ema
from crypto_trend.models import Candle
from crypto_trend.research import candidate_configs, candidate_configs_v2, candidate_configs_v3
from crypto_trend.paper import _paper_summary


class IndicatorTests(unittest.TestCase):
    def test_ema_seed_and_length(self):
        result = ema([1, 2, 3, 4, 5], 3)
        self.assertTrue(math.isnan(result[0]))
        self.assertEqual(result[2], 2)
        self.assertEqual(len(result), 5)

    def test_donchian_excludes_current_bar(self):
        upper, lower = donchian_previous([1, 2, 9, 4], [0, 1, 2, 3], 2)
        self.assertEqual(upper[2], 2)
        self.assertEqual(lower[2], 0)

    def test_atr_constant_range(self):
        result = atr([2] * 20, [1] * 20, [1.5] * 20, 14)
        self.assertEqual(result[-1], 1)


class BacktestTests(unittest.TestCase):
    @staticmethod
    def candles(count=1000):
        return [
            Candle(i * 3_600_000, 100 + i * 0.1, 101 + i * 0.1, 99 + i * 0.1, 100.5 + i * 0.1, 10)
            for i in range(count)
        ]

    def test_resample(self):
        bars, mapping = resample_4h(self.candles(8))
        self.assertEqual(len(bars), 2)
        self.assertEqual(mapping, [0, 0, 0, 0, 1, 1, 1, 1])

    def test_backtest_returns_summary(self):
        result = run(self.candles(), Config())
        self.assertEqual(result["initial_equity"], 10_000)
        self.assertIn("max_drawdown_pct", result)
        self.assertIn("sharpe_365", result)
        self.assertIn("benchmark_buy_hold_pct", result)

    def test_research_has_three_strategy_families(self):
        families = {config.strategy for config in candidate_configs()}
        self.assertEqual(families, {"trend_breakout", "trend_pullback", "volatility_breakout"})
        self.assertEqual(len(candidate_configs()), 48)

    def test_v2_is_long_only_and_four_hour(self):
        configs = candidate_configs_v2()
        self.assertEqual(len(configs), 48)
        self.assertTrue(all(not c.allow_short for c in configs))
        self.assertTrue(all(c.entry_timeframe == "4h" for c in configs))

    def test_four_hour_backtest_runs(self):
        result = run(self.candles(2000), Config(entry_timeframe="4h", allow_short=False))
        self.assertEqual(result["config"]["entry_timeframe"], "4h")

    def test_v3_uses_regime_and_volatility_controls(self):
        configs = candidate_configs_v3()
        self.assertEqual(len(configs), 48)
        self.assertTrue(all(c.regime_filter != "none" for c in configs))
        self.assertTrue(all(c.target_daily_vol is not None for c in configs))

    def test_daily_regime_backtest_runs(self):
        config = Config(entry_timeframe="4h", allow_short=False, regime_filter="daily_ema200", target_daily_vol=0.025)
        result = run(self.candles(6000), config)
        self.assertEqual(result["config"]["regime_filter"], "daily_ema200")

    def test_paper_mode_keeps_open_position(self):
        config = Config(entry_timeframe="4h", allow_short=False, adx_min=0)
        result = run(self.candles(2000), config, close_at_end=False)
        self.assertEqual(result["open_position_at_end"], result["position_state"] is not None)

    def test_paper_summary_before_start_has_zero_costs(self):
        result = run(self.candles(1000), Config(), trade_start_ms=10**15, close_at_end=False)
        summary = _paper_summary(result)
        self.assertEqual(summary["total_fees_usdt"], 0.0)
        self.assertEqual(summary["total_funding_usdt"], 0.0)


if __name__ == "__main__":
    unittest.main()
