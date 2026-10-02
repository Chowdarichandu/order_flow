"""Plain-language EXPLORATORY report from frozen, out-of-sample-only scout outputs."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import numpy as np
from .edge_strategies import load_variants


def classify_family(common:dict|None,extended:dict|None)->str:
    """Frozen screen: after-cost loss is NO EDGE; short/weak evidence is WEAK.

    PROMISING requires positive common and extended CAGR, common and extended
    Sharpe>=.5, common DSR probability>=.95,>=100 common realized lot fragments,
    >=3 full extended OOS years, and >55% positive extended calendar years.
    This is a screening convention, not empirical validation on untouched data.
    """
    if not common:return 'WEAK'
    cagr=common.get('cagr');move=common.get('average_move_pct');cost=common.get('average_cost_pct')
    if cagr is not None and (cagr<=0 or (move is not None and cost is not None and move<=cost)):
        return 'NO EDGE'
    years=list((extended or {}).get('annual_returns',{}).values())
    if (cagr is not None and cagr>0 and (common.get('sharpe') or -999)>=.5
        and (common.get('deflated_sharpe_probability') or 0)>=.95 and common.get('trades',0)>=100
        and extended and (extended.get('cagr') or -999)>0 and (extended.get('sharpe') or -999)>=.5
        and len(years)>=3 and np.mean(np.array(years)>0)>.55):return 'PROMISING'
    return 'WEAK'


def _number(value,digits=2,percent=False):
    return '—' if value is None else f'{value*(100 if percent else 1):.{digits}f}'+('%' if percent else '')


def _year(value):
    return '—' if not value else f"{value['year']}: {_number(value['return'],percent=True)}"


def build_report(results_path:str|Path,*,destination:str|Path='docs/EDGE_SCOUT_REPORT.md',cache_dir:str|Path='data/edge_scout')->str:
    """Render only stored OOS metrics; selection parameters remain training winners."""
    data=json.loads(Path(results_path).read_text());cache=Path(cache_dir)
    if any(record.get('status','').startswith('DEFERRED') for record in data.get('variants',[])):
        raise ValueError('unfinished hourly screen cannot become the final report')
    rows=sorted(data['families'],key=lambda item:-(item['common_oos'] or {}).get('sharpe',-999) if (item['common_oos'] or {}).get('sharpe') is not None else 999)
    variants={variant.id:variant for variant in load_variants()}
    quality={}
    for name in ('daily','hourly'):
        path=cache/f'quality_{name}.json'
        if path.exists():quality[name]=json.loads(path.read_text())
    dataset_hashes={name:hashlib.sha256((cache/f'candles_{name}.parquet').read_bytes()).hexdigest() for name in ('daily','hourly') if (cache/f'candles_{name}.parquet').exists()}
    count={family:sum(variant.family==family for variant in variants.values()) for family in range(1,9)}
    text='''# EDGE SCOUT — EXPLORATORY

Research only. This screen downloads public historical candles; it never uses a
broker token, websocket or order endpoint. Findings are hypotheses for independent
local verification, not completion of the local system's setup/validation roadmap.

## Ranked complete common out-of-sample year: 2025

Ranking is after-cost Sharpe of each family's annual rolling training selector.
Each test choice was fixed using only the preceding three calendar years. All
families share the complete 2025 test year, avoiding a comparison between decades
of daily evidence and one year of hourly evidence. 2026 is a separately labeled
partial diagnostic and is excluded from this ranking and complete-year metrics.
A high rank is not a claim that a family passes the PROMISING screen.

| Rank | Family | Variants counted | Verdict | CAGR | Max DD | Sharpe | Deflated Sharpe probability | Trades | Win % | Average hold days | Average move / cost % | Best / worst year |
|---|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|
'''
    for rank,row in enumerate(rows,1):
        stats=row['common_oos'] or {};verdict=classify_family(row['common_oos'],row['extended_oos'])
        text+=f"| {rank} | {row['name']} | {count[row['family']]} | {verdict} | {_number(stats.get('cagr'),percent=True)} | {_number(stats.get('max_drawdown'),percent=True)} | {_number(stats.get('sharpe'))} | {_number(stats.get('deflated_sharpe_probability'),percent=True)} | {stats.get('trades',0)} | {_number(stats.get('win_pct'))} | {_number(stats.get('average_hold_days'))} | {_number(stats.get('average_move_pct'))} / {_number(stats.get('average_cost_pct'))} | {_year(stats.get('best_year'))} / {_year(stats.get('worst_year'))} |\n"
    text+='''
Trade counts are FIFO realized lot fragments, so partial exits count separately.
Win rate, holding time and move/cost averages are unweighted fragment averages.
Tiny partial lots can dominate the cost average; it is not the portfolio expense
ratio. A positive portfolio return can therefore fail the fragment-cost screen.
CAGR includes cash days; Sharpe uses daily equity returns, 252 sessions/year and
zero risk-free rate. Deflated Sharpe is a probability, not a modified ratio: all
60 registered trials count, including losing/unavailable variants. Its scale
uses cross-trial Sharpe dispersion on this same 2025 OOS period, skew/kurtosis,
and a conservative AR(1) effective-sample approximation. One year is a short
sample; this correction does not remove universe, data-quality or regime bias.

## Longer available OOS history and partial diagnostic

Only complete annual tests appear below. The daily candidate set is available
before 2025; hourly and certified pre-holiday candidates become eligible only
in 2025 because their three-year training data/calendars start in 2022. The
family selector therefore had fewer eligible variants in older folds. Periods
and candidate pools differ: this table is supporting evidence, not the common
ranking. Best/worst years here refer only to complete OOS years.
Missing selected-winner years are omitted, never replaced with another variant
or filled with zero returns. CAGR is suppressed when those years interrupt the
history; pooled valid-fold Sharpe/drawdown are not a continuous calendar account.

| Family | Complete OOS years | CAGR | Max DD | Sharpe | Trades | Best year | Worst year | 2026 partial compounded return |
|---|---|---:|---:|---:|---:|---|---|---:|
'''
    for row in rows:
        stats=row['extended_oos'] or {};years=stats.get('annual_returns',{});partial=row.get('partial_2026') or {};ret=partial.get('annual_returns',{}).get('2026')
        period=f"{min(years)}–{max(years)} ({len(years)})" if years else 'none'
        missing=sorted(set(range(int(min(years)),int(max(years))+1))-{int(year) for year in years}) if years else []
        if missing:period+='; missing '+','.join(map(str,missing))
        cagr='— (gap)' if missing else _number(stats.get('cagr'),percent=True)
        text+=f"| {row['name']} | {period} | {cagr} | {_number(stats.get('max_drawdown'),percent=True)} | {_number(stats.get('sharpe'))} | {stats.get('trades',0)} | {_year(stats.get('best_year'))} | {_year(stats.get('worst_year'))} | {_number(ret,percent=True)} |\n"
    text+='''
The 2026 diagnostic ends on 2026-10-01 and assumes liquidation at the final
observed open. It is not a completed one-year test. Each fold begins with INR
1,000,000 cash; normalized returns compound across independently restarted folds.
Those metrics do not represent one uninterrupted fixed-share cash account.
Terminal exits use the final open, submitted at the preceding close. No final
close or future open is used. Warmup uses only past observations. Missing final
execution prices invalidate the affected fold rather than fabricate a flat exit.

## Bull / bear / sideways OOS results — 2025

Regimes are descriptive, determined using the preceding Nifty50 close: BULL is
above its 200-session SMA and positive 63-session return; BEAR is below and
negative; other complete inputs are SIDEWAYS. Missing warmup is UNCLASSIFIED.
Each cell is conditional compounded return / Sharpe / number of daily samples.
Regime dates are noncontiguous, so no regime CAGR is claimed.

| Family | Bull | Bear | Sideways | Unclassified samples |
|---|---|---|---|---:|
'''
    for row in rows:
        regime=row.get('regimes',{});cells=[]
        for name in ('BULL','BEAR','SIDEWAYS'):
            stats=regime.get(name,{})
            cells.append(f"{_number(stats.get('total_return'),percent=True)} / {_number(stats.get('sharpe'))} / {stats.get('observations',0)}")
        text+=f"| {row['name']} | {' | '.join(cells)} | {regime.get('UNCLASSIFIED',{}).get('observations',0)} |\n"
    text+='''
## Plain-words family verdicts — EXPLORATORY

The verdict rule was set before viewing returns. PROMISING requires positive
common and extended CAGR, both Sharpes at least 0.5, common deflated-Sharpe
probability at least 95%, at least 100 common realized fragments, at least three
complete extended OOS years and more than 55% positive extended years. NO EDGE
means nonpositive common CAGR or average gross move no greater than average
cost. Other cases are WEAK. These thresholds are screening choices, not a
trained classifier or an untouched final holdout.

'''
    for row in rows:
        verdict=classify_family(row['common_oos'],row['extended_oos'])
        reason={'PROMISING':'Passed the frozen after-cost screen; current-survivor and adjustment uncertainty still require untouched local verification.','NO EDGE':'The common test lost after costs or its average gross move did not clear average cost. It should not receive deployment priority.','WEAK':'The available result does not meet the evidence thresholds; positive returns alone are insufficient, especially with only one complete common test year.'}[verdict]
        stats=row['common_oos'] or {}
        if verdict=='NO EDGE' and (stats.get('cagr') or 0)>0:
            reason=f"The portfolio gained {_number(stats['cagr'],percent=True)} after costs, but unweighted fragment move {_number(stats.get('average_move_pct'))}% versus cost {_number(stats.get('average_cost_pct'))}% failed the frozen screen. Tiny partial lots can dominate that average; this does not mean the portfolio lost. Validate capital-weighted move/cost before interpreting this label."
        text+=f"- **{row['name']} — {verdict}:** {reason}\n"
    text+='''
## HANDOFF — top three verification candidates, EXPLORATORY

These are the three highest common-period family ranks, even if their verdict is
WEAK or NO EDGE. They are not three approved edges. For each, the exact variant
below is the **2026 training winner**, chosen on 2023–2025 data; if unavailable,
the latest completed-fold training winner is shown. No best-OOS parameter is
substituted. Run the frozen parameters on an untouched local period, using
point-in-time constituents, verified corporate actions/dividends, dated calendars
and actual contract-note costs before interpreting any apparent improvement.

Common execution: long-only integer shares; next-bar-open entry; INR1m fold
capital; 20-position limit, 10% target cap, gross exposure <=100%; calendar
constituent baskets allow50 positions. Fixed-entry families allow10 positions.
All targets/costs and training rules remain as preregistered. Keep all candidate
variants counted; do not revise parameters from these OOS outcomes.

'''
    rules={
        1:'At each month-end decision close, rank stocks by close[−skip]/close[−(skip+lookback)]−1. Select top names equally, cap each at10%; unfilled slots stay cash. Rebalance at the next observed session open, then hold shares until the next scheduled monthly decision.',
        2:'Enter when close is strictly above the highest prior252-session high, volume is at least the specified multiple of mean prior20-session volume, and close is above the specified trailing SMA. Rank simultaneous entries by fractional breakout, allow10names at10% each, hold the declared number of sessions, and require one flat close decision before renewal.',
        3:'Compute exact Wilder RSI2. Enter when RSI is strictly below the specified threshold and close is above the specified trailing SMA. Rank lowest RSI first; allow10names at10% each. Hold the declared sessions, then emit a flat decision before renewal.',
        4:'Confirm strict swing highs/lows only after the specified left and right bars close; ties are not pivots. Enter on a close crossing above the latest confirmed swing high. Exit at next open after a close crosses below latest confirmed swing low, or after the declared holding sessions. Daily and60-minute confirmation use their own bars; no FVG is used.',
        5:'At the weekly decision close, subtract mapped sector price-index return from stock simple close return over the declared trailing sessions. Rank top names equally at1/top, capped10%; unavailable sector inputs exclude that stock. Next-session-open weekly rebalance; hold shares between decisions.',
        6:'At the weekly decision close, rank ascending sample standard deviation(ddof1) of daily simple close returns over the declared trailing sessions. Select top names equally at1/top, capped10%; next-session-open weekly rebalance and hold shares between decisions.',
        7:'Require the actual09:15 first regular hourly bar. Compare its open with the previous session daily close: go needs a positive gap above the threshold; fade needs a negative gap below minus the threshold. First-bar close must exceed its open. Enter next hourly open, rank largest absolute gap first, allow10names at10%, and hold declared sessions with a flat cooldown before renewal.',
        8:'Equal-weight available CURRENTNifty50 constituents, with50-position limit. Turn-of-month holds the declared last/first session windows; preholiday forms two sessions before a holiday known from an already published circular and enters the last preholiday session open. Replay calendar amendments as of each decision close; apply all per-stock delivery fees.'
    }
    for rank,row in enumerate(rows[:3],1):
        chosen=[record for record in data['selections'] if record['family']==row['family']]
        latest=max(chosen,key=lambda record:record['test_year']) if chosen else None
        if latest:
            variant=variants[latest['selected_variant']]
            common_choice=next((record['selected_variant'] for record in chosen if record['test_year']==2025),'unavailable')
            text+=f"{rank}. **{row['name']}** ({classify_family(row['common_oos'],row['extended_oos'])}): `{variant.id}`, `{variant.timeframe}`. Training interval {latest['test_year']-3}-01-01 to {latest['test_year']-1}-12-31. The ranked 2025 family result used `{common_choice}`; it is not attributed to a different latest recipe. Exact parameters: `{json.dumps(dict(variant.parameters),sort_keys=True)}`. Exact rule: {rules[row['family']]} Calendar decisions use the last known session of the month/ISOweek from dated circulars; execution always lags one bar. Full definitions remain in [EDGE_SCOUT_STRATEGIES.md](EDGE_SCOUT_STRATEGIES.md).\n"
    text+='''
Local verification must include capital-weighted gross move/cost and total
portfolio fee drag alongside the unweighted fragment statistics. Match the
vendor hourly grid, including its final 15:15–15:30 partial bar; a local engine
that emits only complete 60-minute bars needs an explicit conversion and matched
ablation, rather than silently dropping the final bar and claiming equivalence.

## Costs, data and limitations

- Delivery STT0.1% each side; stamp0.015% buy; SEBI0.0001% each side; GST18% on
  eligible fees; brokerage INR20 per order; sell DP INR20 per security/day plus
  GST; slippage **0.1% each side**. NSE exchange/IPFT bundle0.00332% Apr–Sep2024 and0.00307% fromOct2024
  onward (the component split changes inMar2026). BeforeApr2024 the model
  projects0.00297% exchange plus dated IPFT; it is not a verified historical invoice. Cost formula and
  authoritative sources are in [EDGE_SCOUT_ENGINE.md](EDGE_SCOUT_ENGINE.md) and
  [EDGE_SCOUT_REVIEW.md](EDGE_SCOUT_REVIEW.md). Additional contract-note
  charges are not certified by this model; IPFT is included in the dated bundle.
- Current Nifty200/Nifty50 constituents and current sector mappings are used
  throughout history: **survivorship and membership look-ahead bias**. Delisted
  and former constituents are absent. Named sector proxies are not exact historic
  industry portfolios. Some current sector-index histories are backcast before
  product launch; historical publication/membership availability is not certified.
  Historical data includes possible legacy instrument
  splices and unusual index backcasts. The after-cost statistics are conditional
  on this biased universe, not investable historical performance.
- Prices are used as served, without synthetic split/dividend adjustments.
  **Corporate-action adjustment status is UNKNOWN**; dividends/total returns are
  not established. Large changes may be market moves or actions. Local handoff
  must reconcile both prices and shares. No future-detected whole-symbol filter
  was used to conceal this issue.
- 565 distinct conflicting session rows (569 conflicting source observations)
  have missing OHLCV in the research panel; all
  source records and flags remain in raw caches. Missing observations remain
  NaN, no future filling or skipped-trade reconstruction. Missing-price orders
  retry only the original unresolved security budget; valuation uses known marks
  with stale flags. Every missing symbol-period is listed in
  [EDGE_SCOUT_MISSING.csv](EDGE_SCOUT_MISSING.csv), including empty retention/
  prelisting-unknown windows, intraperiod missing sessions and price conflicts.
- All download requests use an explicit User-Agent, no Authorization/token and
  at most5requests/sec with cached backoff retries. Empirical public GETs returned
  successfully, while official V3 examples show Bearer authorization; anonymous
  access is observed behavior, not a guaranteed future API contract. Raw payloads
  and normalized data stay under gitignored `data/edge_scout/`.
- Only regular weekday sessions are modeled. Verified2022–2026 Muhurat dates are
  excluded from regular execution; other historic special-session timing is not
  fully certified. Hourly vendor15:15 candle is only15minutes. Dated NSE annual
  holidays and amendments are replayed as of their conservative publication
  availability, with preholiday evaluation limited to certified-calendar folds.
- Gap fade is long-only recovery after a negative gap. No short cash-equity or
  derivative strategy was simulated. Calendar returns are a current equal-weight
  Nifty50 constituent basket proxy with per-stock costs, not the nontradable
  Nifty50 price index. Basket costs/capacity differ from an ETF.

## Reproduction and recorded evidence

```bash
python -m pip install -e '.[dev,research]'
python -m orderflow.research.edge_data --through 2026-10-01
python -m orderflow.research.edge_scout
python -m orderflow.research.edge_report
pytest -q
```

No keys or secrets are required. Cache hashes detect revised source/data/rules;
completed folds resume only with matching fingerprints. These public source
files can change later, so preserving the original ignored cache is required
for byte-identical reproduction. The preregistered variant ledger, per-fold
training selections and OOS metric snapshot are committed under `docs/`.

'''
    text+=f"Registry SHA256: `{data['registry_sha256']}`. Counted trials: **{data['registered_trials']}**. Final screen runtime: {data['elapsed_seconds']:.2f}s (cache reuse disclosed by fingerprints).\n\n"
    for name,digest in dataset_hashes.items():text+=f"- {name} dataset SHA256: `{digest}`\n"
    text+=f"\nInvalid folds explicitly recorded: **{len(data['failed_folds'])}**; details in `EDGE_SCOUT_INVALID_FOLDS.csv`. Data coverage/quality counts and source hashes are in [EDGE_SCOUT_DATA.md](EDGE_SCOUT_DATA.md).\n"
    Path(destination).write_text(text)
    Path('docs/EDGE_SCOUT_RESULTS.json').write_text(json.dumps(data,indent=2,allow_nan=False))
    import pandas as pd
    pd.DataFrame(data['variants']).to_csv('docs/EDGE_SCOUT_VARIANTS.csv',index=False)
    pd.DataFrame(data['selections']).to_csv('docs/EDGE_SCOUT_FOLD_SELECTIONS.csv',index=False)
    pd.DataFrame(data['failed_folds'],columns=['variant','test_year','reason']).to_csv('docs/EDGE_SCOUT_INVALID_FOLDS.csv',index=False)
    return text


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--results',default='data/edge_scout/results/results.json');parser.add_argument('--destination',default='docs/EDGE_SCOUT_REPORT.md')
    args=parser.parse_args();build_report(args.results,destination=args.destination)

if __name__=='__main__':main()
