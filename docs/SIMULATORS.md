# T01 offline simulator and decoder

The simulator emits official Upstox V3 FeedResponse protobuf bytes. Production
and simulated decoding share `decode/feed.py`; no alternate wire format exists.
Upstox SDK version: 2.30.0.
Generated V3 module SHA-256: `df2cb2a54a01c6c8aed8e7c69fc09aeb55b0daaf9135f11cce36b5a334df2f01`.
The SDK version is pinned in pyproject.toml.

Normal frames include a tick-aligned equity, Nifty 50, Bank Nifty and India VIX;
the 50-stock benchmark includes all three context instruments. Depth is 5 or 30
levels. Trend/range paths and order-book quantities are deterministic. These are
controlled test fixtures, not calibrated replicas of real NSE microstructure.

Fault scenarios: gap, cumulative-volume reset, duplicate, out-of-order snapshot,
transport disconnect, HTTP 403 and expired token (401). Auth faults are simulated
HTTP responses; disconnects are explicit transport exceptions. No network,
OAuth secrets, websocket connection or order-placement call is made.

Decoder counters and flags retain quality anomalies; stale and duplicate frames
do not overwrite the per-instrument/session high-watermark state. Gap thresholds
are configurable at decoder construction. IndexFullFeed has no vtt/depth, so
these fields stay null/empty. LTPC-only and first-level modes are also supported.
Candle fixtures preserve quality anomalies and map closed OHLCV to the canonical
Arrow schema. Historical availability is the download receipt time; future-open
candles and invalid OHLC are rejected. Candle-based research derived from those
bars must use APPROXIMATE labels in later layers.

Tests: 20 T01 test cases, 30 tests in the full suite, all passing. This includes
V3 serialization and canonical Arrow schemas; quality faults and counters;
context instruments; both depths; first-level/LTPC; session reset; malformed
payload, unknown instrument, naive timestamps and open candles; candle known
answers and truncation; deterministic replay and HTTP User-Agent enforcement.

Benchmark: 21,600 snapshots over a simulated six-hour session, 50 stocks plus
three context instruments, 1,144,800 decoded rows. Generation plus Arrow decode
completed in 38.17 seconds at
29,992 ticks/second on this Cloud environment.
This measures generation/decoding only; recorder I/O and queue behavior await T03.
See `benchmarks/T01.json` for raw results.

```bash
python -m pytest
PYTHONPATH=src python scripts/benchmark_t01.py
```
