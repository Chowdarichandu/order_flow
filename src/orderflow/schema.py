"""Versioned Arrow contracts for BOOTSTRAP.md sections 3 and 4.

Prices use fixed decimals; instrument master supplies the tick size. Timestamps
are UTC microseconds. Derived records include availability and provenance. Arrow
specifies storage types, not causal ordering: producers must validate aware input
timestamps and input availability before building tables. Raw snapshots remain
intact, including quality flags; no schema implies deduplication or interpolation.
"""
from collections.abc import Sequence
from typing import Final

import pyarrow as pa

TIMESTAMP: Final = pa.timestamp('us', tz='UTC')
PRICE: Final = pa.decimal128(24, 8)
QUANTITY: Final = pa.int64()
FLAGS: Final = pa.list_(pa.string())
DEPTH_LEVEL: Final = pa.struct([
    pa.field('price', PRICE, nullable=False),
    pa.field('quantity', QUANTITY, nullable=False),
    pa.field('orders', pa.int32()),
])
INPUT_REFERENCE: Final = pa.struct([
    pa.field('record_id', pa.string(), nullable=False),
    pa.field('available_at', TIMESTAMP, nullable=False),
])
ZONE_COMPONENT: Final = pa.struct([
    pa.field('record_id', pa.string(), nullable=False),
    pa.field('type', pa.string(), nullable=False),
    pa.field('low', PRICE, nullable=False),
    pa.field('high', PRICE, nullable=False),
    pa.field('created_at', TIMESTAMP, nullable=False),
    pa.field('available_at', TIMESTAMP, nullable=False),
])
KEY_FIELDS: Final = (
    pa.field('symbol', pa.string(), nullable=False),
    pa.field('instrument_key', pa.string(), nullable=False),
    pa.field('session_date', pa.date32(), nullable=False),
)
PROVENANCE_FIELDS: Final = (
    pa.field('source', pa.string(), nullable=False),
    pa.field('method', pa.string(), nullable=False),
    pa.field('confidence', pa.string(), nullable=False),
    pa.field('flags', FLAGS, nullable=False),
    pa.field('available_at', TIMESTAMP, nullable=False),
    pa.field('inputs', pa.list_(INPUT_REFERENCE), nullable=False),
)


def _contract(name: str, fields: Sequence[pa.Field]) -> pa.Schema:
    """Section 3: every stage reads/writes versioned Arrow data contracts only."""
    return pa.schema(fields, metadata={
        b'orderflow.schema_version': b'1',
        b'orderflow.contract': name.encode('ascii'),
    })


def _derived(name: str, fields: Sequence[pa.Field]) -> pa.Schema:
    """Section 1 rule 9: every derived value carries an availability timestamp."""
    return _contract(name, [*KEY_FIELDS, *fields, *PROVENANCE_FIELDS])


INSTRUMENT_SCHEMA: Final = _contract('instrument', [
    pa.field('instrument_key', pa.string(), nullable=False),
    pa.field('symbol', pa.string(), nullable=False),
    pa.field('segment', pa.string(), nullable=False),
    pa.field('instrument_type', pa.string(), nullable=False),
    pa.field('tick_size', PRICE, nullable=False),
    pa.field('lot_size', QUANTITY, nullable=False),
    pa.field('sector', pa.string()),
    pa.field('available_at', TIMESTAMP, nullable=False),
])
RAW_MESSAGE_SCHEMA: Final = _contract('raw_message', [
    pa.field('connection_id', pa.string(), nullable=False),
    pa.field('sequence', pa.int64(), nullable=False),
    pa.field('receipt_ts', TIMESTAMP, nullable=False),
    pa.field('payload', pa.binary(), nullable=False),
    pa.field('source', pa.string(), nullable=False),
    pa.field('flags', FLAGS, nullable=False),
])
TICK_SCHEMA: Final = _contract('tick', [
    *KEY_FIELDS,
    pa.field('sequence', pa.int64(), nullable=False),
    pa.field('ltp', PRICE),
    pa.field('ltq', QUANTITY),
    pa.field('ltt', TIMESTAMP),
    pa.field('vtt', QUANTITY),
    pa.field('oi', QUANTITY),
    pa.field('bids', pa.list_(DEPTH_LEVEL), nullable=False),
    pa.field('asks', pa.list_(DEPTH_LEVEL), nullable=False),
    pa.field('tbq', QUANTITY),
    pa.field('tsq', QUANTITY),
    pa.field('exchange_ts', TIMESTAMP),
    pa.field('receipt_ts', TIMESTAMP, nullable=False),
    pa.field('source', pa.string(), nullable=False),
    pa.field('flags', FLAGS, nullable=False),
])
CANDLE_SCHEMA: Final = _derived('candle', [
    pa.field('bar_start', TIMESTAMP, nullable=False),
    pa.field('bar_end', TIMESTAMP, nullable=False),
    pa.field('timeframe_minutes', pa.int32(), nullable=False),
    *[pa.field(name, PRICE, nullable=False) for name in ('open', 'high', 'low', 'close')],
    pa.field('volume', QUANTITY, nullable=False),
    pa.field('oi', QUANTITY),
])
TRADE_SCHEMA: Final = _derived('trade', [
    pa.field('sequence', pa.int64(), nullable=False),
    pa.field('exchange_ts', TIMESTAMP),
    pa.field('receipt_ts', TIMESTAMP, nullable=False),
    pa.field('price', PRICE, nullable=False),
    pa.field('volume', QUANTITY, nullable=False),
    pa.field('side', pa.string(), nullable=False),
    pa.field('quote_ts', TIMESTAMP),
])
BAR_SCHEMA: Final = _derived('bar', [
    pa.field('bar_id', pa.string(), nullable=False),
    pa.field('bar_kind', pa.string(), nullable=False),
    pa.field('bar_start', TIMESTAMP, nullable=False),
    pa.field('bar_end', TIMESTAMP, nullable=False),
    pa.field('timeframe_minutes', pa.int32()),
    pa.field('volume_target', QUANTITY),
    *[pa.field(name, PRICE) for name in ('open', 'high', 'low', 'close', 'mid_close')],
    *[pa.field(name, QUANTITY, nullable=False) for name in
      ('volume', 'buy_volume', 'sell_volume', 'unknown_volume', 'delta', 'cvd')],
])
FOOTPRINT_SCHEMA: Final = _derived('footprint', [
    pa.field('bar_id', pa.string(), nullable=False),
    pa.field('price', PRICE, nullable=False),
    pa.field('bid_volume', QUANTITY, nullable=False),
    pa.field('ask_volume', QUANTITY, nullable=False),
    pa.field('unknown_volume', QUANTITY, nullable=False),
    pa.field('buy_imbalance', pa.bool_(), nullable=False),
    pa.field('sell_imbalance', pa.bool_(), nullable=False),
    pa.field('stacked_buy', pa.bool_(), nullable=False),
    pa.field('stacked_sell', pa.bool_(), nullable=False),
])
FEATURE_SCHEMA: Final = _derived('feature', [
    pa.field('minute', TIMESTAMP, nullable=False),
    pa.field('name', pa.string(), nullable=False),
    pa.field('level', pa.int32()),
    pa.field('value', pa.float64()),
    pa.field('r_squared', pa.float64()),
    pa.field('n', pa.int64()),
    pa.field('unknown_share', pa.float64()),
    pa.field('window_start', TIMESTAMP),
    pa.field('window_end', TIMESTAMP),
])
PROFILE_SCHEMA: Final = _derived('profile', [
    pa.field('minute', TIMESTAMP, nullable=False),
    pa.field('profile_kind', pa.string(), nullable=False),
    pa.field('sessions', pa.int32(), nullable=False),
    pa.field('levels', pa.list_(pa.struct([
        pa.field('price', PRICE, nullable=False),
        pa.field('volume', pa.float64(), nullable=False),
    ])), nullable=False),
    *[pa.field(name, PRICE) for name in ('poc', 'vah', 'val', 'vwap', 'ib_high', 'ib_low')],
    pa.field('hvn', pa.list_(PRICE), nullable=False),
    pa.field('lvn', pa.list_(PRICE), nullable=False),
])
LEVEL_SCHEMA: Final = _derived('level', [
    pa.field('record_id', pa.string(), nullable=False),
    pa.field('type', pa.string(), nullable=False),
    pa.field('timeframe_minutes', pa.int32()),
    pa.field('low', PRICE, nullable=False),
    pa.field('high', PRICE, nullable=False),
    pa.field('side', pa.string(), nullable=False),
    pa.field('origin_at', TIMESTAMP, nullable=False),
    pa.field('created_at', TIMESTAMP, nullable=False),
    pa.field('invalidated_at', TIMESTAMP),
    pa.field('mitigated_at', TIMESTAMP),
    pa.field('state', pa.string(), nullable=False),
])
CONTEXT_SCHEMA: Final = _derived('context', [
    pa.field('minute', TIMESTAMP, nullable=False),
    pa.field('index_regime', pa.string()),
    pa.field('vix_regime', pa.string()),
    pa.field('sector_rs_open', pa.float64()),
    pa.field('sector_rs_5d', pa.float64()),
    pa.field('breadth_above_vwap_fraction', pa.float64()),
    pa.field('advancers', pa.int32()),
    pa.field('decliners', pa.int32()),
    pa.field('time_of_day', pa.string()),
    pa.field('liquidity_tier', pa.int8()),
    pa.field('event_flags', FLAGS, nullable=False),
])
ZONE_SCHEMA: Final = _derived('zone', [
    pa.field('zone_id', pa.string(), nullable=False),
    pa.field('minute', TIMESTAMP, nullable=False),
    pa.field('low', PRICE, nullable=False),
    pa.field('high', PRICE, nullable=False),
    pa.field('components', pa.list_(ZONE_COMPONENT), nullable=False),
    pa.field('distinct_types', pa.int32(), nullable=False),
    pa.field('created_at', TIMESTAMP, nullable=False),
    pa.field('freshness_minutes', pa.float64(), nullable=False),
    pa.field('touches', pa.int32(), nullable=False),
    pa.field('side', pa.string(), nullable=False),
    pa.field('invalidation_price', PRICE, nullable=False),
    pa.field('invalidated_at', TIMESTAMP),
])
EVENT_SCHEMA: Final = _derived('event', [
    pa.field('event_id', pa.string(), nullable=False),
    pa.field('event_type', pa.string(), nullable=False),
    pa.field('occurred_at', TIMESTAMP, nullable=False),
    pa.field('confirmed_at', TIMESTAMP, nullable=False),
    pa.field('price', PRICE, nullable=False),
    pa.field('side', pa.string(), nullable=False),
    pa.field('strength', pa.float64()),
    pa.field('zone_id', pa.string()),
])
SETUP_SCHEMA: Final = _derived('setup', [
    pa.field('setup_id', pa.string(), nullable=False),
    pa.field('setup_type', pa.string(), nullable=False),
    pa.field('tier', pa.string(), nullable=False),
    pa.field('formed_at', TIMESTAMP, nullable=False),
    pa.field('zone_id', pa.string(), nullable=False),
    pa.field('side', pa.string(), nullable=False),
    *[pa.field(name, PRICE, nullable=False) for name in ('entry', 'stop', 'target')],
    pa.field('reward_risk', pa.float64(), nullable=False),
    pa.field('round_trip_cost_bps', pa.float64(), nullable=False),
    pa.field('spread', PRICE, nullable=False),
    pa.field('research_quantity', QUANTITY),
    pa.field('accepted', pa.bool_(), nullable=False),
    pa.field('rejection_reasons', FLAGS, nullable=False),
    pa.field('forced_exit_at', TIMESTAMP, nullable=False),
])
SHADOW_SIGNAL_SCHEMA: Final = _derived('shadow_signal', [
    pa.field('signal_id', pa.string(), nullable=False),
    pa.field('setup_id', pa.string(), nullable=False),
    pa.field('logged_at', TIMESTAMP, nullable=False),
    pa.field('zone_components', pa.list_(ZONE_COMPONENT), nullable=False),
    pa.field('context_inputs', pa.list_(INPUT_REFERENCE), nullable=False),
    pa.field('orderflow_inputs', pa.list_(INPUT_REFERENCE), nullable=False),
    pa.field('triggered', pa.bool_(), nullable=False),
    pa.field('variant_id', pa.string(), nullable=False),
])
OUTCOME_SCHEMA: Final = _derived('outcome', [
    pa.field('signal_id', pa.string(), nullable=False),
    pa.field('horizon_minutes', pa.int32()),
    pa.field('at_session_close', pa.bool_(), nullable=False),
    pa.field('observed_at', TIMESTAMP, nullable=False),
    pa.field('gross_return', pa.float64()),
    pa.field('net_return', pa.float64()),
    pa.field('cost_bps', pa.float64(), nullable=False),
])
QUALITY_SCHEMA: Final = _contract('quality', [
    pa.field('session_date', pa.date32(), nullable=False),
    pa.field('symbol', pa.string(), nullable=False),
    pa.field('reported_at', TIMESTAMP, nullable=False),
    *[pa.field(name, pa.int64(), nullable=False) for name in
      ('received', 'written', 'dropped', 'gaps', 'resets', 'duplicates',
       'out_of_order', 'disconnects')],
    pa.field('max_lag_ms', pa.float64()),
    pa.field('flags', FLAGS, nullable=False),
])
SCHEMAS: Final[dict[str, pa.Schema]] = {
    'instrument': INSTRUMENT_SCHEMA, 'raw_message': RAW_MESSAGE_SCHEMA,
    'tick': TICK_SCHEMA, 'candle': CANDLE_SCHEMA, 'trade': TRADE_SCHEMA,
    'bar': BAR_SCHEMA, 'footprint': FOOTPRINT_SCHEMA, 'feature': FEATURE_SCHEMA,
    'profile': PROFILE_SCHEMA, 'level': LEVEL_SCHEMA, 'context': CONTEXT_SCHEMA,
    'zone': ZONE_SCHEMA, 'event': EVENT_SCHEMA, 'setup': SETUP_SCHEMA,
    'shadow_signal': SHADOW_SIGNAL_SCHEMA, 'outcome': OUTCOME_SCHEMA,
    'quality': QUALITY_SCHEMA,
}
DERIVED_SCHEMAS: Final = frozenset(SCHEMAS) - {'instrument', 'raw_message', 'tick', 'quality'}
