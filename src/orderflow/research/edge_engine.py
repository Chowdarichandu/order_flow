"""EXPLORATORY cash-equity simulator; no broker, websocket, or order routing code.

A target is available at its row's close and may execute only at the next
observed row's open. OHLC bars remain APPROXIMATE historical observations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CostModel:
    """Delivery charges in INR: STT both sides and conservative slippage each side.

    Stamp duty applies on buys; GST applies to brokerage, exchange/IPFT, SEBI and
    sell-side DP fees. Defaults are explicit research assumptions, not a tariff
    guarantee. DP is charged once per security per sell day, including exits.
    """
    stt: float = .001
    stamp_buy: float = .00015
    exchange: float = .0000297
    sebi: float = .000001
    gst: float = .18
    brokerage_per_order: float = 20.
    brokerage_cap_rate: float | None = None
    dp_sell: float = 20.
    slippage: float = .001

    def __post_init__(self):
        if any(v is not None and (not np.isfinite(v) or v < 0) for v in self.__dict__.values()):
            raise ValueError('Cost parameters must be finite and nonnegative')
        if self.slippage >= 1:
            raise ValueError('slippage must be less than one')

    def fees(self, notional: float, side: str, *, apply_dp: bool = True, timestamp=None) -> float:
        """Exact additive statutory/broker cost, excluding price slippage."""
        if side not in ('BUY', 'SELL') or not np.isfinite(notional) or notional < 0:
            raise ValueError('Invalid order side or notional')
        if notional == 0:
            return 0.
        brokerage = (self.brokerage_per_order if self.brokerage_cap_rate is None else
                     min(self.brokerage_per_order, self.brokerage_cap_rate * notional))
        exchange_rate = self.exchange
        ipft_rate = 0.
        # Published latest historical switch; earlier periods explicitly project
        # the 2024 tariff. Explicit custom exchange rates remain constant.
        if timestamp is not None and self.exchange == .0000297:
            tariff_day = pd.Timestamp(timestamp).tz_convert("Asia/Kolkata").date()
            if tariff_day >= pd.Timestamp("2026-03-01").date():
                exchange_rate = .0000307
            elif pd.Timestamp("2024-04-01").date() <= tariff_day < pd.Timestamp("2024-10-01").date():
                exchange_rate = .0000322
            if tariff_day < pd.Timestamp("2026-03-01").date():
                ipft_rate = .000001 if tariff_day >= pd.Timestamp("2023-04-01").date() else .000000001
        # From March 2026 .0000307 is already the exchange/IPFT bundle.
        # Custom exchange rates are explicitly inclusive all-in projections.
        exchange = (exchange_rate + ipft_rate) * notional
        sebi = self.sebi * notional
        dp = self.dp_sell if side == 'SELL' and apply_dp else 0.
        return (self.stt * notional + (self.stamp_buy * notional if side == 'BUY' else 0.)
                + brokerage + exchange + sebi + dp + self.gst * (brokerage + exchange + sebi + dp))


@dataclass(frozen=True)
class PortfolioLimits:
    """Long-only integer shares, bounded name count and target weight, no leverage."""
    initial_capital: float = 1_000_000.
    max_positions: int = 20
    max_position_weight: float = .10
    terminal_liquidation: bool = True

    def __post_init__(self):
        if (not np.isfinite(self.initial_capital) or self.initial_capital <= 0
                or self.max_positions <= 0 or not 0 < self.max_position_weight <= 1):
            raise ValueError('Invalid portfolio limits')


@dataclass
class BacktestResult:
    returns: pd.Series
    equity: pd.Series
    trades: pd.DataFrame
    orders: pd.DataFrame
    audit: dict[str, Any] = field(default_factory=dict)


ORDER_COLUMNS = ['timestamp', 'signal_available_at', 'symbol', 'side', 'quantity',
                 'raw_open', 'fill_price', 'fees', 'cash_after', 'terminal']
TRADE_COLUMNS = ['symbol', 'entry_time', 'exit_time', 'quantity', 'entry_price',
                 'exit_price', 'hold_days', 'gross_move_pct', 'cost_pct', 'gross_pnl',
                 'total_cost', 'net_pnl', 'entry_fees', 'exit_fees']


def backtest(panel, target_weights: np.ndarray, costs: CostModel = CostModel(),
             limits: PortfolioLimits = PortfolioLimits(), *,
             rebalance_mask: np.ndarray | None = None) -> BacktestResult:
    """Execute close-time long-only targets on next open, with exact cash accounting.

    Without a mask, a changed target row triggers rebalancing; unchanged targets
    hold existing shares. A supplied mask supports scheduled rebalancing even if
    constituents are unchanged. All-NaN rows mean HOLD. Terminal liquidation is
    known at the previous close and executes at the final open. A missing final
    open leaves the position outstanding and is reported, never fabricated.
    """
    times = pd.DatetimeIndex(panel.times)
    if times.tz is None or not times.is_monotonic_increasing or times.has_duplicates:
        raise ValueError('Times must be aware, increasing and unique')
    opens, closes = np.asarray(panel.open, float), np.asarray(panel.close, float)
    weights = np.asarray(target_weights, float)
    if opens.shape != closes.shape or weights.shape != opens.shape or len(times) != len(opens):
        raise ValueError('Panel and target shapes must agree')
    if np.any(np.isinf(weights)) or np.any(np.isfinite(weights) & (weights < 0)):
        raise ValueError('Targets must be finite nonnegative weights or all-NaN HOLD rows')
    holds = np.isnan(weights).all(axis=1)
    if np.any(np.isnan(weights).any(axis=1) & ~holds):
        raise ValueError('Partial NaN target rows are invalid')
    t_count, n_symbols = opens.shape
    # Public timestamps are bar starts; record when the prior close is available.
    hourly = len(times) > 1 and np.min(np.diff(times.asi8)) < pd.Timedelta(hours=20).value
    session_ends = times.tz_convert('Asia/Kolkata').normalize() + pd.Timedelta(hours=15, minutes=30)
    availability = pd.DatetimeIndex(np.minimum((times + pd.Timedelta(hours=1)).asi8, session_ends.asi8), tz='UTC') if hourly else session_ends.tz_convert('UTC')
    tradable = np.asarray(panel.tradable, bool)
    if tradable.shape != (n_symbols,) or len(panel.symbols) != n_symbols:
        raise ValueError('Symbol/tradable dimensions disagree')
    if rebalance_mask is None:
        mask = np.zeros(t_count, bool)
        previous = np.zeros(n_symbols)
        for t, target in enumerate(weights):
            if not holds[t]:
                mask[t] = not np.array_equal(target, previous)
                previous = target
    else:
        mask = np.asarray(rebalance_mask, bool)
        if mask.shape != (t_count,):
            raise ValueError('Rebalance mask must have one value per row')
    quantities = np.zeros(n_symbols, np.int64)
    last_mark = np.full(n_symbols, np.nan)
    lots: list[list[dict]] = [[] for _ in range(n_symbols)]
    cash = float(limits.initial_capital)
    equities = np.zeros(t_count)
    orders: list[dict] = []
    trades: list[dict] = []
    dp_charged: set[tuple[str, Any]] = set()
    audit: dict[str, Any] = dict(minimum_cash=cash, missing_open_order_attempts=0,
        stale_valuation_observations=0, missing_initial_valuation_observations=0,
        target_position_limit_truncations=0, target_weight_clips=0,
        partial_buy_orders_cash_limited=0, unaffordable_sell_order_attempts=0, terminal_unliquidated_positions=0,
        signal_timing='previous bar close -> next observed bar open',
        terminal_policy='last open, submitted at preceding close',
        returns_frequency='daily close in Asia/Kolkata', initial_capital=cash)

    pending_notional = np.full(n_symbols, np.nan)
    pending_available_at = np.full(n_symbols, None, dtype=object)

    def sell(symbol_index: int, quantity: int, row: int, terminal: bool):
        nonlocal cash
        raw = opens[row, symbol_index]
        fill = raw * (1 - costs.slippage)
        symbol = panel.symbols[symbol_index]
        dp_key = (symbol, times[row].tz_convert('Asia/Kolkata').date())
        fee = costs.fees(quantity * fill, 'SELL', apply_dp=dp_key not in dp_charged, timestamp=times[row])
        if cash + quantity * fill < fee:
            audit["unaffordable_sell_order_attempts"] += 1
            return False
        dp_charged.add(dp_key)
        cash += quantity * fill - fee
        quantities[symbol_index] -= quantity
        orders.append(dict(timestamp=times[row], signal_available_at=pending_available_at[symbol_index], symbol=symbol,
            side='SELL', quantity=quantity, raw_open=raw, fill_price=fill, fees=fee,
            cash_after=cash, terminal=terminal))
        remaining = quantity
        while remaining:
            lot = lots[symbol_index][0]
            piece = min(remaining, lot['quantity'])
            entry_fee = lot['fees_per_share'] * piece
            exit_fee = fee * piece / quantity
            gross = piece * (raw - lot['raw_open'])
            cost = piece * ((lot['fill_price'] - lot['raw_open']) + (raw - fill)) + entry_fee + exit_fee
            basis = piece * lot['raw_open']
            trades.append(dict(symbol=symbol, entry_time=lot['time'], exit_time=times[row],
                quantity=piece, entry_price=lot['fill_price'], exit_price=fill,
                hold_days=(times[row]-lot['time']).total_seconds()/86400,
                gross_move_pct=100 * gross / basis, cost_pct=100 * cost / basis,
                gross_pnl=gross, total_cost=cost, net_pnl=gross-cost,
                entry_fees=entry_fee, exit_fees=exit_fee))
            remaining -= piece
            lot['quantity'] -= piece
            if not lot['quantity']:
                lots[symbol_index].pop(0)
        return True

    for t in range(t_count):
        # Current opens may mark current holdings for sizing; all signals remain t-1.
        valid_open = np.isfinite(opens[t]) & (opens[t] > 0)
        last_mark[valid_open] = opens[t, valid_open]
        terminal = limits.terminal_liquidation and t_count >= 2 and t == t_count - 1
        fresh_signal = bool(t and mask[t-1] and not holds[t-1])
        if t and (fresh_signal or terminal) and times[t] < availability[t-1]:
            raise ValueError('Next open predates previous signal availability')
        if t and (terminal or fresh_signal):
            target = np.zeros(n_symbols) if terminal else weights[t-1].copy()
            target[~tradable] = 0
            audit['target_weight_clips'] += int(np.sum(target > limits.max_position_weight))
            target = np.minimum(target, limits.max_position_weight)
            eligible = np.flatnonzero(target > 0)
            if len(eligible) > limits.max_positions:
                # Stable symbol order resolves equal target weights deterministically.
                ranked = eligible[np.argsort(-target[eligible], kind='stable')]
                target[ranked[limits.max_positions:]] = 0
                audit['target_position_limit_truncations'] += len(eligible) - limits.max_positions
            if target.sum() > 1:
                target /= target.sum()
            value = cash + np.nansum(quantities * last_mark)
            # Freeze each symbol's intended budget at the scheduled open. Missing
            # prices leave only that symbol pending; other fills never rebalance
            # merely because an unrelated security recovers its open later.
            pending_notional[:] = np.nan
            wanting = (target > 0) | (quantities > 0)
            pending_notional[wanting] = value * target[wanting]
            pending_available_at[wanting] = availability[t-1]
        if t and np.isfinite(pending_notional).any():
            attempting = np.isfinite(pending_notional)
            audit['missing_open_order_attempts'] += int(np.sum(attempting & ~valid_open))
            executable = attempting & valid_open
            original_notional = pending_notional.copy()
            desired = quantities.copy()
            desired[executable] = np.floor(pending_notional[executable] / opens[t, executable]).astype(np.int64)
            pending_notional[executable] = np.nan
            for j in np.flatnonzero(valid_open & (desired < quantities)):
                sold = sell(int(j), int(quantities[j]-desired[j]), t, terminal)
                if not sold and not terminal:
                    pending_notional[j] = original_notional[j]
            for j in np.flatnonzero(valid_open & (desired > quantities)):
                if not tradable[j] or terminal:
                    continue
                # Missing-price holdings count toward the actual name cap.
                if quantities[j] == 0 and np.count_nonzero(quantities) >= limits.max_positions:
                    continue
                fill = opens[t, j] * (1 + costs.slippage)
                wanted = int(desired[j]-quantities[j])
                low, high = 0, min(wanted, int(max(cash, 0)/fill))
                while low < high:
                    mid = (low + high + 1)//2
                    if mid * fill + costs.fees(mid*fill, 'BUY', timestamp=times[t]) <= cash + 1e-9:
                        low = mid
                    else:
                        high = mid - 1
                quantity = low
                if quantity < wanted:
                    audit['partial_buy_orders_cash_limited'] += 1
                if not quantity:
                    continue
                fee = costs.fees(quantity * fill, 'BUY', timestamp=times[t])
                cash -= quantity * fill + fee
                if -1e-8 < cash < 0:
                    cash = 0.
                quantities[j] += quantity
                lots[j].append(dict(quantity=quantity, fees_per_share=fee/quantity,
                    raw_open=opens[t, j], fill_price=fill, time=times[t]))
                orders.append(dict(timestamp=times[t], signal_available_at=pending_available_at[j],
                    symbol=panel.symbols[j], side='BUY', quantity=quantity,
                    raw_open=opens[t,j], fill_price=fill, fees=fee, cash_after=cash, terminal=False))
        valid_close = np.isfinite(closes[t]) & (closes[t] > 0)
        audit['stale_valuation_observations'] += int(np.sum((quantities > 0) & ~valid_close))
        last_mark[valid_close] = closes[t, valid_close]
        audit['missing_initial_valuation_observations'] += int(np.sum((quantities > 0) & ~np.isfinite(last_mark)))
        equities[t] = cash + np.nansum(quantities * last_mark)
        audit['minimum_cash'] = min(audit['minimum_cash'], cash)
        if cash < -1e-7:
            raise AssertionError('Cash became negative')
    audit['terminal_unliquidated_positions'] = int(np.count_nonzero(quantities)) if limits.terminal_liquidation else 0
    audit['final_cash'] = cash
    audit['open_positions'] = {panel.symbols[j]: int(q) for j, q in enumerate(quantities) if q}
    equity = pd.Series(equities, index=times, name='equity')
    # Hourly variants have the same annualization basis as daily families.
    if len(equity):
        days = equity.index.tz_convert('Asia/Kolkata').normalize().tz_convert('UTC')
        daily = equity.groupby(days).last()
        returns = daily.pct_change()
        returns.iloc[0] = daily.iloc[0] / limits.initial_capital - 1
    else:
        returns = pd.Series(dtype=float, name='return')
    returns.name = 'return'
    return BacktestResult(returns, equity, pd.DataFrame(trades, columns=TRADE_COLUMNS),
                          pd.DataFrame(orders, columns=ORDER_COLUMNS), audit)


def rolling_folds(times, train_years: int = 3, test_years: int = 1) -> list[dict]:
    """Calendar rolling 3-year training / nonoverlapping 1-year test intervals.

    All bounds are half-open UTC timestamps. Last partial test years are omitted;
    selection must use training returns only and portfolios restart flat.
    """
    dates = pd.DatetimeIndex(times)
    if dates.tz is None or train_years < 1 or test_years < 1:
        raise ValueError('Aware dates and positive fold durations required')
    if not len(dates):
        return []
    start = dates.min().normalize()
    end = dates.max().normalize() + pd.Timedelta(days=1)
    test_start = start + pd.DateOffset(years=train_years)
    folds = []
    while test_start + pd.DateOffset(years=test_years) <= end:
        folds.append(dict(train_start=test_start-pd.DateOffset(years=train_years),
            train_end=test_start, test_start=test_start,
            test_end=test_start+pd.DateOffset(years=test_years)))
        test_start += pd.DateOffset(years=test_years)
    return folds


def _effective_n(returns: pd.Series) -> float:
    """Conservative AR(1) approximation; negative autocorrelation grants no bonus."""
    n = len(returns)
    rho = returns.autocorr(1) if n > 2 else 0
    rho = float(np.clip(rho, 0, .99)) if np.isfinite(rho) else 0.
    return max(3., min(float(n), n*(1-rho)/(1+rho)))


def deflated_sharpe_probability(returns: pd.Series, total_trials: int,
                               trial_sharpes: list[float] | None = None) -> float | None:
    """Bailey/Lopez de Prado DSR probability with registered-trial correction.

    Trial sharpes, if supplied, are annualized daily values. Their cross-trial
    SD supplies the expected-max null scale; otherwise 1/sqrt(effective_n-1)
    is a disclosed sampling-null fallback. Skew/kurtosis and AR(1) effective
    sample size are estimated only from evaluated returns.
    """
    r = pd.Series(returns).dropna()
    if total_trials < 1:
        raise ValueError('Every registered trial must be counted')
    if len(r) < 30 or r.std(ddof=1) <= 0:
        return None
    n = _effective_n(r)
    sr = r.mean()/r.std(ddof=1)
    if trial_sharpes is not None:
        values = np.asarray(trial_sharpes, float)/np.sqrt(252)
        values = values[np.isfinite(values)]
        scale = np.std(values, ddof=1) if len(values) > 1 else 1/np.sqrt(n-1)
    else:
        scale = 1/np.sqrt(n-1)
    if total_trials == 1:
        expected = 0.
    else:
        gamma = .5772156649015329
        normal = NormalDist()
        expected = scale*((1-gamma)*normal.inv_cdf(1-1/total_trials)
                          + gamma*normal.inv_cdf(1-1/(total_trials*np.e)))
    skew, kurtosis = r.skew(), r.kurt()+3
    denominator = 1-skew*sr+(kurtosis-1)*sr*sr/4
    if denominator <= 0 or not np.isfinite(denominator):
        return None
    z = (sr-expected)*np.sqrt(n-1)/np.sqrt(denominator)
    return float(NormalDist().cdf(z))


def _return_metrics(returns: pd.Series) -> dict:
    r = returns.dropna()
    if not len(r):
        return dict(cagr=None, max_drawdown=None, sharpe=None)
    wealth = (1+r).cumprod()
    # Include starting capital in the drawdown watermark.
    peak = wealth.cummax().clip(lower=1)
    duration = ((r.index[-1]-r.index[0]).total_seconds()/86400+1)/365.25
    cagr = float(wealth.iloc[-1]**(1/duration)-1) if duration > 0 and wealth.iloc[-1] > 0 else None
    return dict(cagr=cagr, max_drawdown=float((wealth/peak-1).min()),
                sharpe=float(np.sqrt(252)*r.mean()/r.std(ddof=1)) if len(r)>1 and r.std(ddof=1)>0 else None)


def summarize(result: BacktestResult, total_trials: int,
              trial_sharpes: list[float] | None = None) -> dict:
    """After-cost OOS-only metrics, with FIFO realized-lot trade accounting."""
    out = _return_metrics(result.returns)
    trades = result.trades
    out.update(trades=len(trades), orders=len(result.orders),
        win_pct=float(100*(trades.net_pnl > 0).mean()) if len(trades) else None,
        average_hold_days=float(trades.hold_days.mean()) if len(trades) else None,
        average_move_pct=float(trades.gross_move_pct.mean()) if len(trades) else None,
        average_cost_pct=float(trades.cost_pct.mean()) if len(trades) else None,
        net_pnl=float(trades.net_pnl.sum()) if len(trades) else 0.,
        deflated_sharpe_probability=deflated_sharpe_probability(result.returns, total_trials, trial_sharpes),
        total_registered_trials=total_trials, return_observations=len(result.returns),
        effective_observations=_effective_n(result.returns) if len(result.returns) else 0.,
        label='EXPLORATORY', trade_count_definition='FIFO realized lot fragments; partial exits counted separately')
    annual = result.returns.groupby(result.returns.index.tz_convert('Asia/Kolkata').year).apply(lambda x: (1+x).prod()-1)
    out['annual_returns'] = {str(k):float(v) for k,v in annual.items()}
    out['best_year'] = {'year':int(annual.idxmax()), 'return':float(annual.max())} if len(annual) else None
    out['worst_year'] = {'year':int(annual.idxmin()), 'return':float(annual.min())} if len(annual) else None
    return out


def regime_metrics(result: BacktestResult, benchmark_close: pd.Series) -> dict:
    """Causal daily regimes: prior close vs 200DMA and prior 63-session return.

    BULL requires both above/positive; BEAR both below/negative; other complete
    inputs are SIDEWAYS. Missing warmup is UNCLASSIFIED. Conditional CAGR is
    deliberately omitted because regime observations are discontinuous.
    """
    benchmark = benchmark_close.sort_index()
    ma = benchmark.rolling(200, min_periods=200).mean()
    momentum = benchmark.pct_change(63, fill_method=None)
    labels = pd.Series('UNCLASSIFIED', index=benchmark.index)
    valid = ma.notna() & momentum.notna() & benchmark.notna()
    labels.loc[valid] = 'SIDEWAYS'
    labels.loc[valid & (benchmark > ma) & (momentum > 0)] = 'BULL'
    labels.loc[valid & (benchmark < ma) & (momentum < 0)] = 'BEAR'
    labels = labels.shift(1)
    day_index = labels.index.tz_convert('Asia/Kolkata').normalize().tz_convert('UTC')
    labels = pd.Series(labels.to_numpy(), index=day_index).groupby(level=0).last()
    labels = labels.reindex(result.returns.index).fillna('UNCLASSIFIED')
    output = {}
    for name in ('BULL','BEAR','SIDEWAYS','UNCLASSIFIED'):
        r = result.returns[labels == name]
        summary = _return_metrics(r)
        output[name] = dict(observations=len(r), total_return=float((1+r).prod()-1) if len(r) else None,
                            sharpe=summary['sharpe'], max_drawdown=summary['max_drawdown'])
    return output
