# Exact definitions

4.1 Order flow (live tier)
   Per-tick volume: v_t = vtt_t - vtt_{t-1} ; negative or reset -> 0, flag
    VOLUME_RESET .
   First tick -> 0, flag FIRST_TICK .
   Aggressor (quote rule, tick fallback): last quote strictly before the trade, p = ltp :
    p >= ask1 BUY/HIGH; p <= bid1 SELL/HIGH; p > mid BUY/MEDIUM; p < mid
   SELL/MEDIUM;
   otherwise tick rule vs last different price -> BUY/SELL/LOW; else UNKNOWN (reported
   separately).
   Delta = buy_vol - sell_vol per bar; CVD from session open; unknown_vol per bar.
   Footprint: per bar, per tick-aligned price: bid_vol (sell-aggressor), ask_vol (buy-
   aggressor).
   Diagonal imbalance: buy at p if ask_vol(p) >= R*bid_vol(p-tick) and ask_vol(p)
   >= min_vol ;
   sell at p if bid_vol(p) >= R*ask_vol(p+tick) and bid_vol(p) >= min_vol . R=3.0;
   min_vol = 20th percentile of level volume so far that day. Stacked: >= 3 consecutive
   levels.
   Depth imbalance L: (sum bid_qty - sum ask_qty)/(sum bid_qty + sum ask_qty) ,
   levels 1..L.
   OFI (Cont-Kukanov-Stoikov), level 1:
    e_n = 1[Pb_n>=Pb_{n-1}]qb_n - 1[Pb_n<=Pb_{n-1}]qb_{n-1} - 1[Pa_n<=Pa_{n-
   1}]qa_n + 1[Pa_n>=Pa_{n-1}]qa_{n-1} ;
   OFI(interval) = sum e_n. Multi-level OFI: same per level m=1..L, each normalized by
   trailing
   average depth at that level; report per level and the sum.
   Sweep (book): best ask (bid) moves through >= k previously displayed levels in one
   snapshot interval with volume > 0. k=3.
   Iceberg (heuristic): level stays at best bid/ask; traded volume there > F x max
   displayed
   qty (F=3) with >= 2 refills.
   Absorption: in W=3 bars, volume within 1 tick of a level >= A x median level volume
   (A=3), aggressor volume dominant INTO the level, price not beyond it by > 2 ticks.
   Exhaustion: new N=20-bar extreme with |bar delta| >= 90th pct of the day so far, and
   no
   extension within M=3 bars (confirmed after those bars).
   Delta divergence: higher swing high with lower CVD high (bearish); lower low with
   higher
   CVD low (bullish); swings confirmed per 4.4.
   VPIN: volume buckets V = trailing 20-day avg daily volume / 50; per bucket
   |V_buy - V_sell|/V ; mean of last 50 buckets; UNKNOWN split evenly, share reported.

   Kyle's lambda: rolling 30 x 1-minute OLS slope of mid return on delta, with R^2 and n.


4.2 Volume profile
   Session profile: volume per tick-aligned price (ticks live; history: each 1-minute bar's
   volume spread evenly across its high-low range, labelled APPROXIMATE).
   POC = max-volume price (tie -> nearest session VWAP). Value area: expand from POC
   toward the side with more volume until 70% covered -> VAL/VAH.
   Developing POC/VAH/VAL each minute from data up to that minute.
   HVN/LVN: local max/min of the 3-tick smoothed profile.
   Composite profiles: last 5 and 20 sessions.
   Naked POC: a prior session POC not traded since; carried forward until touched.
   Initial balance: high/low of the first 60 minutes; IB extensions as multiples of IB range.


4.3 VWAP zones
   Session VWAP = sum(p*v)/sum(v) (ticks live; history uses typical price (H+L+C)/3 x bar
   volume, APPROXIMATE).
   Bands: sigma = sqrt(sum v*(p - VWAP)^2 / sum v); bands at +/-1, 2, 3 sigma.
   Anchored VWAPs from: session open, gap open, prior-day high and low bars, each
   confirmed
   swing high/low (4.4), event times (results/announcements), week and month open.
   VWAP events: reclaim (close back above after >= 2 closes below), rejection (touch and
   close away), band tag (+/-2 or 3 sigma touch), band acceptance (>= 3 closes beyond a
   band).
4.4 SMC (timeframes 1m, 5m, 15m, 60m)
   Swing high/low: fractal with N=2 bars each side; confirmed only after N bars close.
   Structure: trend from the sequence of confirmed swings. BOS: close beyond the last
   swing in the trend direction. CHoCH: first close beyond the last swing AGAINST the
   trend.
   Close-based by default (wick option in config).
   Displacement: bar range >= 1.5 x ATR(14) and body >= 60% of range.
   Order block (bullish): last down-close candle before a displacement leg that produced
   a
   bullish BOS; zone = that candle's [low, high] (or [low, open] by config). Mitigated on first
   return; invalidated on a close below its low. Mirror for bearish.
   FVG (bullish): low of bar 3 > high of bar 1; gap [high1, low3]; minimum size >= 2 ticks
   and

       = 0.1 x ATR. Partially filled when traded into; fully filled on close below high1. Mirror
       for bearish.

   Liquidity pools: equal highs/lows (>= 2 confirmed swings within 0.1 x ATR), prior
   day/week
   high/low, session high/low, IB high/low.
   Liquidity sweep: trade beyond a pool by >= 1 tick, then close back inside within M=3
   bars
   -> SWEEP_REVERSAL; closes beyond for M bars -> SWEEP_CONTINUATION
   (acceptance).
   Premium/discount: within the current dealing range (last confirmed swing low to high):
   above 50% premium, below discount; OTE = 62-79% retracement.
   Multi-timeframe bias: 60m and 15m structure direction; aligned / mixed / opposed.


4.5 Levels
Prior day high/low/close, prior week high/low, opening ranges (5/15/30 min), gap size and
gap-fill status, round numbers off by default.


4.6 Context
   Index regime: Nifty 50 and Bank Nifty 15m structure + position vs session VWAP ->
   TREND_UP / TREND_DOWN / RANGE.
   Volatility regime: India VIX percentile over 1 year -> LOW / NORMAL / HIGH.
   Relative strength: stock return minus its sector index return, since open and over 5
   days.
   Breadth: % of the universe above session VWAP; advancers/decliners.
   Time of day: OPEN (09:15-09:45), MORNING, MIDDAY, AFTERNOON, CLOSE (14:45-
   15:15).
   Liquidity tier: median traded value and median spread over 20 days -> tiers 1-3.
   Event flags: results day, announcement in the last 60 min, expiry day, budget day.


4.7 Zone engine
At each minute, collect every active level/zone (OB, FVG, POC/VAH/VAL, naked POC, HVN,
VWAP
and bands, anchored VWAPs, prior-day levels, liquidity pools) as price intervals. Cluster
those
within 0.25 x ATR(14, 5m) into zones. Each zone records: price range, components by
type,
count of distinct types, freshness (minutes since created), touches, the side it serves
(support/resistance), and an invalidation price. Zones are LOCATION context, not votes.


4.8 Setups (pre-registered; parameters in config)
   S1 Sweep and reclaim: liquidity sweep reversal into a zone with >= 2 component types;
   trigger = absorption or delta flip at the zone (live tier) or reclaim close (history tier).
   S2 Retest in discount: OB/FVG retest in discount (premium for shorts) with aligned
   15m/60m
   bias and VWAP on the trade side; trigger = positive OFI/delta (live) or rejection close
   (history).
   S3 VWAP band reversion: +/-2 sigma tag in a RANGE regime with exhaustion or
   absorption;
   target VWAP.
   S4 Acceptance breakout: acceptance beyond VAH/PDH (VAL/PDL) in a TREND regime
   with stacked
   imbalances and rising CVD (live) or 3 closes beyond (history); target next zone or IB
   extension.
   S5 Naked POC magnet: in a direction-confirmed move, target the nearest naked POC.
   Trade plan for every setup: stop beyond the zone invalidation + buffer (0.1 x ATR);
   target
   = next opposing zone or liquidity pool; reject if reward/risk < 1.5 or target distance
   < 3 x round-trip cost + spread. Size by volatility (risk per trade in config). Forced exit
   15:15.
4.9 Validation
   History tier (2022 onward, candles): S1-S5 without order flow triggers, purged
   walk-forward, costs at 10/20/30 bps, gross and net PF, folds profitable, loss autopsy.
   Live tier (recordings): every setup forming live is logged in the shadow signal ledger
   with
   zone components, context, order flow state at bar close, and outcomes at +5/15/60 min
   and at
   the close. Formal evaluation at 20 and 60 recorded days: does the order flow trigger
   improve
   outcomes vs untriggered setups, after costs?
   Every variant counted; holdout used once; layers added only through ablation; retired
   ideas
   get an autopsy. Edge board: docs/EDGE_BOARD.md .
