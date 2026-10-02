# Arrow contract conventions

All contracts are in `src/orderflow/schema.py`, version 1. Every schema has its
name and version in metadata. Arrow IPC schema serialization and the tick Parquet round-trip tests pass under
PyArrow 25.0.1. Producers and consumers await their roadmap tasks.

Prices are `decimal128(24, 8)`, quantities are signed 64-bit integers, and
timestamps are UTC microseconds. Tick alignment comes from the instrument
master. Session dates use Asia/Kolkata trading dates. Historical profile
allocations use floating volumes to preserve fractional uniform allocations.
Missing feed values remain null; absent depth is an empty list.

Every derived record requires `available_at`, source, method, confidence, flags
and input references with availability times. Consumers may only see records
whose availability is at or before their evaluation cutoff. Producers must
reject naive timestamps, compute availability from every input and confirming
bar, and enforce this ordering: Arrow's storage types do not enforce causal
semantics or string enumerations. These runtime checks belong to subsequent
tasks and cannot be inferred from a timestamp field alone.

Use `ESTIMATE` for snapshot-derived trades, aggressor, delta and footprints;
`HEURISTIC` for icebergs; `APPROXIMATE` for candle-based VWAP and profile.
Trade sides are BUY/SELL/UNKNOWN; confidence is HIGH/MEDIUM/LOW/UNKNOWN.
UNKNOWN volume is stored separately in bars and footprints. VPIN separately
reports its unknown share. Raw payloads and quality flags remain preserved.

Raw messages carry connection sequence, receipt time and protobuf bytes. Tick
rows carry exchange and receipt times, cumulative volume, last quantity and
configurable depth lists. Raw Parquet partitioning and protobuf decoding await
T01/T03/T05; no wire format has been fabricated.

Confirmed structures store origin, creation and availability separately.
Research plans and shadow signals contain no order placement command or API.
Outcomes are separate records and must not be joined to features before their
own availability. Quality counters distinguish received/written/dropped,
gaps/resets/duplicates/out-of-order and disconnects.
