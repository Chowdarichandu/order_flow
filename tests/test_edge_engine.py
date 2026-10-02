from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from orderflow.research.edge_engine import (
    CostModel, PortfolioLimits, backtest, deflated_sharpe_probability,
    regime_metrics, rolling_folds, summarize,
)


def panel(opens, closes=None, symbols=('A',), tradable=None):
    opens = np.asarray(opens, dtype=float).reshape(-1, len(symbols))
    close = opens.copy() if closes is None else np.asarray(closes, dtype=float).reshape(opens.shape)
    return SimpleNamespace(times=pd.date_range('2020-01-01', periods=len(opens), tz='UTC'),
                           symbols=symbols, open=opens, high=close, low=close,
                           close=close, volume=np.ones_like(opens),
                           tradable=np.ones(len(symbols), bool) if tradable is None else np.array(tradable))


def zero_cost():
    return CostModel(stt=0, stamp_buy=0, exchange=0, sebi=0, gst=0,
                     brokerage_per_order=0, dp_sell=0, slippage=0)


def limits(**kwargs):
    return PortfolioLimits(initial_capital=1000, max_position_weight=1, **kwargs)


def test_next_open_exact_cash_and_terminal_previous_close_order():
    p = panel([10, 20, 30, 40])
    r = backtest(p, np.ones((4, 1)), zero_cost(), limits())
    assert r.orders.iloc[0]['timestamp'] == p.times[1]
    assert r.orders.iloc[0]['quantity'] == 50
    assert r.orders.iloc[-1]['timestamp'] == p.times[3]
    assert r.equity.tolist() == [1000, 1000, 1500, 2000]
    assert r.trades.iloc[0]['net_pnl'] == 1000
    assert r.trades.iloc[0]['hold_days'] == 2


def test_explicit_delivery_costs_and_integer_cash_safety():
    c = CostModel(brokerage_per_order=20, dp_sell=18.5)
    assert c.fees(10000, 'BUY') == pytest.approx(10 + 1.5 + .297 + .01 + 20 + .18 * (20 + .297 + .01))
    assert c.fees(10000, 'SELL') == pytest.approx(10 + .297 + .01 + 20 + 18.5 + .18 * (20 + .297 + .01 + 18.5))
    r = backtest(panel([10, 10, 10]), np.ones((3, 1)), c, limits())
    assert r.audit['minimum_cash'] >= 0
    assert r.orders.iloc[0]['quantity'] < 100
    assert r.trades['net_pnl'].sum() < 0
    assert r.trades['total_cost'].sum() > 0


def test_missing_open_never_fills_and_missing_close_is_audited():
    p = panel([10, np.nan, 10, 12], [10, np.nan, 10, 12])
    r = backtest(p, np.ones((4, 1)), zero_cost(), limits())
    assert r.orders.iloc[0]['timestamp'] == p.times[2]
    assert r.audit['missing_open_order_attempts'] == 1
    p2 = panel([10, 10, 10, 12], [10, np.nan, 10, 12])
    r2 = backtest(p2, np.ones((4, 1)), zero_cost(), limits())
    assert r2.audit['stale_valuation_observations'] == 1
    assert r2.equity.iloc[1] == 1000


def test_position_limit_tradability_and_negative_targets():
    p = panel([[10]*3]*4, symbols=('A', 'B', 'INDEX'), tradable=[1, 1, 0])
    r = backtest(p, np.ones((4, 3)), zero_cost(), PortfolioLimits(initial_capital=1000, max_positions=1, max_position_weight=.1))
    assert set(r.orders['symbol']) == {'A'}
    assert r.orders.iloc[0]['quantity'] == 10
    with pytest.raises(ValueError, match='nonnegative'):
        backtest(p, -np.ones((4, 3)), zero_cost(), limits())


def test_truncation_keeps_nonterminal_history_identical():
    p = panel([10, 10, 11, 9, 12, 10])
    weights = np.array([[1], [1], [0], [1], [0], [1]])
    a = backtest(p, weights, zero_cost(), limits(terminal_liquidation=False))
    short = panel([10, 10, 11, 9])
    b = backtest(short, weights[:4], zero_cost(), limits(terminal_liquidation=False))
    pd.testing.assert_series_equal(a.equity.iloc[:4], b.equity)
    pd.testing.assert_frame_equal(a.orders[a.orders.timestamp <= short.times[-1]].reset_index(drop=True), b.orders)


def test_walk_forward_three_train_one_test_disjoint():
    dates = pd.date_range('2010-01-01', '2018-12-31', freq='B', tz='UTC')
    folds = rolling_folds(dates)
    assert len(folds) == 6
    first = folds[0]
    assert first['train_start'] == pd.Timestamp('2010-01-01', tz='UTC')
    assert first['test_start'] == pd.Timestamp('2013-01-01', tz='UTC')
    assert first['test_end'] == pd.Timestamp('2014-01-01', tz='UTC')
    assert folds[1]['train_start'] == pd.Timestamp('2011-01-01', tz='UTC')


def test_summary_known_returns_and_no_closed_trade_nan_win():
    r = backtest(panel([10, 10, 12, 15]), np.ones((4, 1)), zero_cost(), limits())
    s = summarize(r, total_trials=240)
    assert s['trades'] == 1
    assert s['win_pct'] == 100
    assert s['average_move_pct'] == pytest.approx(50)
    assert s['average_cost_pct'] == 0
    assert s['max_drawdown'] == 0
    assert s['deflated_sharpe_probability'] is None


def test_deflated_sharpe_trial_penalty():
    returns = pd.Series(np.tile([.01, -.002, .004, -.003], 100))
    one = deflated_sharpe_probability(returns, 1)
    many = deflated_sharpe_probability(returns, 240)
    assert 0 <= many < one <= 1


def test_regime_no_forward_benchmark_classification():
    dates = pd.date_range('2020-01-01', periods=300, tz='UTC')
    benchmark = pd.Series(np.arange(100, 400, dtype=float), index=dates)
    p = panel(np.ones(300)*10)
    result = backtest(p, np.zeros((300, 1)), zero_cost(), limits())
    a = regime_metrics(result, benchmark)
    b = regime_metrics(result, benchmark.iloc[:250])
    assert a['BULL']['observations'] == 100
    assert a['UNCLASSIFIED']['observations'] == 200
    assert b['BULL']['observations'] == 50
    assert b['UNCLASSIFIED']['observations'] == 250


def test_dp_once_per_scrip_per_sell_day_and_actual_signal_close():
    p = panel([10, 10, 10, 10])
    p.times = pd.date_range('2020-01-01 03:45', periods=4, freq='h', tz='UTC')
    c = CostModel(stt=0, stamp_buy=0, exchange=0, sebi=0, gst=.18,
                  brokerage_per_order=0, dp_sell=20, slippage=0)
    r = backtest(p, np.array([[1], [.5], [0], [0]]), c, limits())
    sells = r.orders[r.orders.side == 'SELL']
    assert sells.fees.sum() == pytest.approx(23.6)
    assert r.orders.iloc[0].signal_available_at == p.times[0] + pd.Timedelta(hours=1)
    assert (r.orders.timestamp >= r.orders.signal_available_at).all()


def test_fee_exchange_tariff_cutover_and_small_order_flat_brokerage():
    c = CostModel()
    assert c.fees(10, 'BUY') > 20
    old = c.fees(10000, 'BUY', timestamp=pd.Timestamp('2026-02-28', tz='UTC'))
    new = c.fees(10000, 'BUY', timestamp=pd.Timestamp('2026-03-01', tz='UTC'))
    # Official FA73061 changes the split, retaining the same exchange/IPFT bundle.
    assert new == pytest.approx(old)


def test_scheduled_rebalance_and_hold_rows():
    p = panel([10, 10, 20, 20, 20])
    weights = np.array([[.5], [.5], [.5], [.5], [.5]])
    a = backtest(p, weights, zero_cost(), limits(terminal_liquidation=False))
    b = backtest(p, weights, zero_cost(), limits(terminal_liquidation=False),
                 rebalance_mask=np.ones(5, dtype=bool))
    assert len(a.orders) == 1
    assert len(b.orders) > len(a.orders)
    hold = weights.copy()
    hold[1:4] = np.nan
    assert len(backtest(p, hold, zero_cost(), limits(terminal_liquidation=False)).orders) == 1


def test_verified_april_to_september_2024_exchange_tariff():
    c = CostModel()
    april = c.fees(10000, 'BUY', timestamp=pd.Timestamp('2024-04-01', tz='UTC'))
    october = c.fees(10000, 'BUY', timestamp=pd.Timestamp('2024-10-01', tz='UTC'))
    assert april - october == pytest.approx(.025 * 1.18)


def test_sell_fee_cannot_create_negative_cash_after_extreme_price_collapse():
    p = panel([10, 10, .001])
    c = CostModel(stt=0, stamp_buy=0, exchange=0, sebi=0, gst=0,
                  brokerage_per_order=0, dp_sell=20, slippage=0)
    r = backtest(p, np.ones((3, 1)), c, limits())
    assert r.audit['minimum_cash'] >= 0
    assert r.audit['unaffordable_sell_order_attempts'] == 1
    assert r.audit['terminal_unliquidated_positions'] == 1


def test_missing_name_retry_does_not_rebalance_already_filled_name():
    p = panel([[10, 10], [10, np.nan], [20, np.nan], [30, 10], [30, 10]], symbols=('A', 'B'))
    targets = np.full((5, 2), .5)
    r = backtest(p, targets, zero_cost(), limits(terminal_liquidation=False),
                 rebalance_mask=np.array([1, 0, 0, 0, 0], dtype=bool))
    a_orders = r.orders[r.orders.symbol == 'A']
    assert len(a_orders) == 1
    assert a_orders.iloc[0].quantity == 50
    b_orders = r.orders[r.orders.symbol == 'B']
    assert b_orders.iloc[0].timestamp == p.times[3]
    assert b_orders.iloc[0].quantity == 50
    assert b_orders.iloc[0].signal_available_at == r.orders.iloc[0].signal_available_at


def test_official_nse_ipft_and_exchange_bundle_is_307_per_crore_2025_and_2026():
    c = CostModel(stt=0, stamp_buy=0, sebi=0, brokerage_per_order=0, dp_sell=0)
    old = c.fees(100000, 'BUY', timestamp=pd.Timestamp('2025-01-01', tz='UTC'))
    new = c.fees(100000, 'BUY', timestamp=pd.Timestamp('2026-04-01', tz='UTC'))
    assert old == pytest.approx(3.07 * 1.18)
    assert new == pytest.approx(3.07 * 1.18)
    april_2024 = c.fees(100000, 'BUY', timestamp=pd.Timestamp('2024-04-01', tz='UTC'))
    assert april_2024 == pytest.approx(3.32 * 1.18)
    early_2023 = c.fees(100000, 'BUY', timestamp=pd.Timestamp('2023-03-01', tz='UTC'))
    assert early_2023 == pytest.approx((2.97 + .0001) * 1.18)
    custom = CostModel(stt=0, stamp_buy=0, sebi=0, brokerage_per_order=0, dp_sell=0, exchange=.00005)
    assert custom.fees(100000, 'BUY', timestamp=pd.Timestamp('2025-01-01', tz='UTC')) == pytest.approx(5 * 1.18)
