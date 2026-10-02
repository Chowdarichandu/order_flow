# Architecture

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
