<!-- Extracted verbatim from BOOTSTRAP.pdf with pdftotext -layout; page breaks removed.
PDF table columns and clipped text are retained. See docs/SOURCE_NOTES.md. -->

BOOTSTRAP v2: orderflow-zero
A blank-slate trading research system for NSE cash equities on Upstox, combining
order flow, SMC, volume profile and VWAP zones, with market context, a zone engine,
pre-registered setups and honest validation.

Code is built from zero in Codex Cloud (no network, no secrets, tested against simulators).
It runs on the owner's Linux machine (systemd user services), later possibly a VM in
Mumbai.
Nothing in this repo places orders.




0. The idea in one paragraph
Price reacts at zones where several kinds of levels agree (SMC structure, volume profile,
VWAP bands, prior-day levels). Context decides which zones matter today (index regime,
sector strength, volatility, time of day). Order flow at the zone is the trigger that shows
whether buyers or sellers are actually winning there. Each layer has one job: WHERE
(zones),
WHEN/WHICH (context), NOW (order flow). A trade plan needs a stop beyond the zone's
invalidation
and a target at the next opposing zone that is at least 3x the round-trip cost. Every idea is
proven on data it was never tuned on, or it is dropped.




1. Permanent rules (copy verbatim into AGENTS.md)

Lessons already paid for
 1. Every HTTP call sends an explicit User-Agent (Upstox's Cloudflare blocks Python's
   default
   urllib User-Agent with HTTP 403 / Error 1010).
 2. The access token is read from a 600-permission file at connect time and re-read once
   on
   401/403. No environment handoffs. Never log or print token values.
 3. Never write to disk inside the websocket receive loop: receive -> bounded queue ->
   batched
   writer thread. (Inline writes caused 70 s lag and 43 disconnects in one session.)
 4. Log the status code and sanitized body of every auth/connect failure.
 5. Preflight HARD gates: token missing/expired, or feed-authorize non-200 after retries.
   Everything else is a SOFT alert. Recording is read-only and never blocked by soft
   checks.
 6. One Upstox websocket client owns the feed. Others use REST or read the recorder's
   output.
 7. NSE holiday calendar respected by every scheduled job.
 8. Timestamps tz-aware, compared in UTC, displayed in Asia/Kolkata.
 9. Every derived value carries an availability timestamp; nothing uses data stamped after it.
   Structures (swings, BOS, FVG, sweeps, exhaustion) exist only after their confirming bars
   close.
10. The live feed is snapshot-based: trade size, aggressor side, delta and footprint are
   ESTIMATES with a confidence field. Bar-based history (VWAP, volume profile) is
   APPROXIMATE.
11. Gaps, resets, duplicates and out-of-order messages are flagged and counted, never
   dropped
   silently.
12. Layers have roles, not votes. A layer stays only if a matched ablation shows it improves
   results on unseen data after costs.


How agents work
   Max 2 attempts or 90 minutes per problem; then docs/stuck/<task>.md and move on.
   Tests first: hand-built sequences with known answers for every metric and structure.
   Truncation test for everything time-based: the value at t is unchanged when data after t
   is removed.
   No network, keys or live calls in Cloud tasks; use the simulators.
   One task per commit ("T##: ..."); docs/ROADMAP.md status updated after each.
   Never weaken or delete a test to make it pass.




2. Upstox data sources (what each layer uses)

  Source                           Gives                              Used by

  Market Data Feed V3              ltp, ltq, ltt, cumulative volume   order flow, tick volume
  websocket (full mode; 30-        (vtt), OI, best 5 bid/ask, total   profile, live VWAP, depth
  level depth if plan allows)      buy/sell qty                      metrics

                                   Nifty 50, Bank Nifty, sector
  Same feed, index instruments                                       context layer
                                   indices, India VIX ticks

                                                                     SMC, bar VWAP, bar
                                   1-minute OHLCV from Jan
  Historical Candle V3                                               volume profile, levels,
                                   2022 (stocks and indices)
                                                                     context, backtests

                                   instrument keys, tick size, lot
  Instrument master                                                  everything
                                   size, segment

                                   official daily OHLCV, delivery    validation, delivery
  NSE bhavcopy (public)
                                   %                                 features


Facts: feed authorize returns a websocket URL; messages are protobuf (use the official SDK
classes or the official .proto fetched in setup). Tokens expire daily ~03:30 IST. Concurrent
websocket connections per account are limited. vtt is cumulative and can reset; ltq is
only
the last trade's size; snapshots can skip trades.

Order flow has no history at Upstox. It exists only from the day recording starts, so the
recorder is the first thing deployed, and existing recordings are imported (see T05).




3. Architecture

 ingest/       feed client, recorder, history downloader, importer for existing recordings
 decode/       protobuf -> TickEvent; candles -> Bar
 trades/       per-tick volume, aggressor side + confidence
 bars/         1m/5m/15m/60m time bars, volume bars, from ticks (live) or candles (history)
 layers/
    orderflow/      footprint, delta, CVD, imbalances, depth, OFI, sweeps, icebergs,
                    absorption, exhaustion, divergence, VPIN, Kyle's lambda
    profile/        session/developing/composite profiles, POC/VAH/VAL, HVN/LVN, naked POC,
                    initial balance
    vwap/           session VWAP + sigma bands, anchored VWAPs, weekly VWAP, VWAP events
    smc/            swings, structure, BOS/CHoCH, displacement, order blocks, FVGs,
                    liquidity pools, sweeps, premium/discount, multi-timeframe bias
    levels/         prior day/week high/low/close, opening ranges, gaps
 context/      index regime, India VIX regime, sector relative strength, breadth,
               time of day, liquidity tier, event-day flags
 zones/        zone engine: cluster all levels into zones with components and freshness
 setups/       pre-registered setups S1-S5, trade plans, cost gate
 engine/          ONE code path for live and replay; per-minute point-in-time output
 research/        event study, backtester (history tier), shadow signal ledger (live tier), edge boa
 ops/             systemd units/timers, preflight, alerts, status board, runbook, install script
 ui/              read-only live view


All data contracts in src/orderflow/schema.py (pyarrow). Parameters in
config/default.yaml .




4. Exact definitions

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




5. Roadmap (one commit per task; parallel groups noted)

 Task       Depends   Builds                                          Done when

                      Scaffold: AGENTS.md (section 1 verbatim),
                      docs from sections 0-4, pyproject [dev],
 T00        -                                                         pytest green
                      src/orderflow/, schema.py,
                      config/default.yaml with every parameter

                      Simulators: V3 protobuf feed (trend,
                      range, gaps, resets, out-of-order,              Round-trip and edge-
 T01        T00
                      disconnect, 403, expired token, index           case tests
                      instruments) and candle history; decoders

                                                                      Expired/missing/401/403
                      auth (OAuth, daily refresh to token file),
 T02        T01                                                       tests; User-Agent
                      preflight (hard/soft, retries 08:30-09:10)
                                                                      always set

                                                                      Simulated 6-hour
                      Feed client + recorder (queue, batched
                                                                      session, zero drops,
 T03        T01       writer, crash-safe, lag/drop metrics, quality
                                                                      receive loop never
                      report), stocks + indices + VIX
                                                                      blocked

                      trades + bars (volume, aggressor,
 T04        T01                                                       Known-answer tests
                      confidence; 1/5/15/60m and volume bars)
                 History downloader (Historical Candle V3
                 1-min from 2022, resumable, throttled,      Simulator-backed tests;
T05   T01        User-Agent, gap manifest, bhavcopy          importer round-trip
                 cross-check) + importer for existing raw
                 recordings into this repo's schema

                 Order flow core: footprint, delta, CVD,     Known-answer +
T06   T04
                 diagonal/stacked imbalances                 truncation tests

                 Depth: depth imbalance, OFI, multi-level
T07   T04                                                    Known-answer tests
                 OFI, book sweeps, iceberg

                 Flow events: absorption, exhaustion,        Known-answer tests;
T08   T06
                 divergence, VPIN, Kyle's lambda             confirmation timing

                 Volume profile: session, developing,        Known-answer +
T09   T04
                 composite 5/20, naked POC, HVN/LVN, IB      truncation tests

                 VWAP: session + bands, anchored VWAPs,      Known-answer +
T10   T04
                 weekly/monthly, VWAP events                 truncation tests

                 SMC: swings, structure, BOS/CHoCH,          Known-answer tests per
T11   T04        displacement, OB, FVG, pools, sweeps,       structure; confirmation
                 premium/discount, MTF bias                  timing

                 Levels: prior day/week, opening ranges,
T12   T04                                                    Known-answer tests
                 gaps

                 Context: index regime, VIX regime, sector
T13   T03, T04   RS, breadth, time of day, liquidity tier,   Known-answer tests
                 event flags

                                                             Clustering, freshness
T14   T09-T12    Zone engine
                                                             and invalidation tests

                                                             Each setup triggers on a
      T08,       Setups S1-S5, trade plans, cost gate,
T15                                                          crafted scenario and not
      T13, T14   sizing
                                                             on its near-miss

                 Engine: one live/replay path, per-minute
                                                             Deterministic replay; live
T16   T15        point-in-time output, events and setup
                                                             simulation equals replay
                 tables

                 Research: history-tier backtester (purged   End-to-end on

T17   T16        walk-forward, costs), event study, shadow   simulated data with
                        ledger, edge board, variant ledger            report templates

                        Ops: systemd units/timers (refresh 03:45,
                        preflight 08:30, recorder 09:00-15:35,
           T02,                                                       Install dry-run on a
  T18                   history nightly), holiday calendar, Discord
           T03, T05                                                   clean container
                        alerts, status board, RUNBOOK.md, install
                        script

                        Read-only live view: per symbol, zones,
                                                                      Renders from replay
  T19      T16          VWAP bands, profile, footprint/CVD, recent
                                                                      output
                        events and setups


Parallel groups: [T02, T03, T04, T05] after T01; [T06, T07, T09, T10, T11, T12] after T04;
[T08, T13] next; then T14 -> T15 -> T16 -> [T17, T18, T19].
Deploy early: after T02 + T03 + T18, the owner installs the recorder so live data starts
accumulating while the layers are built.




6. Codex Cloud environment
Setup script ( scripts/codex_setup.sh ):


 set -euo pipefail
 python -m pip install --upgrade pip
 pip install -e ".[dev]" || pip install pytest hypothesis pyarrow polars numpy protobuf websoc
 pip install upstox-python-sdk || true
 # If the SDK lacks the V3 feed protobuf, download the official MarketDataFeedV3.proto from
 # Upstox's documentation into proto/ and compile it with grpcio-tools here.


Agent internet OFF (or Upstox documentation domains only, GET). No secrets.




7. Owner steps on the machine (after T18)
 1. Clone, run the install script.
 2. Put API key/secret/redirect URL and the Discord webhook in the files RUNBOOK.md
   names (600 perms).
 3. Do the first OAuth login once.
 4. Stop the old recorder first (one feed client per account), then start the new recorder.
 5. Import existing recordings (T05 importer) so no recorded days are lost.
6. Run replay on recorded days; enable live research outputs after replay checks pass.
