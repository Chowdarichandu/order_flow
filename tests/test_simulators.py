"""T01 official-wire and fault scenarios, written before implementation."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from google.protobuf.message import DecodeError
from upstox_client.feeder.proto import MarketDataFeedV3_pb2 as pb
from orderflow.sim.feed import FeedSimulator, SimulatedHTTP, SimulatedDisconnect
from orderflow.sim.history import candle_response
from orderflow.decode.feed import Decoder
from orderflow.decode.candles import decode_candles
from orderflow.schema import TICK_SCHEMA, CANDLE_SCHEMA

START = datetime(2026, 10, 1, 3, 45, tzinfo=timezone.utc)


def decode_run(scenario='trend', depth=5, count=8):
    sim = FeedSimulator(start=START, scenario=scenario, depth=depth)
    decoder = Decoder(sim.instruments, gap_seconds=2)
    frames = list(sim.frames(count))
    tables = [decoder.decode(frame) for frame in frames]
    return sim, decoder, frames, tables


@pytest.mark.parametrize('depth', [5, 30])
def test_official_full_feed_round_trip(depth):
    sim, _, frames, tables = decode_run(depth=depth)
    parsed = pb.FeedResponse.FromString(frames[0]['payload'])
    assert parsed.SerializeToString(deterministic=True) == frames[0]['payload']
    assert tables[0].schema.equals(TICK_SCHEMA, check_metadata=True)
    rows = tables[0].to_pylist()
    stock = next(row for row in rows if row['symbol'] == 'TEST')
    assert stock['ltp'] == Decimal('100')
    assert stock['vtt'] == 1000
    assert len(stock['bids']) == depth
    assert stock['bids'][0]['price'] == Decimal('99.95')
    assert stock['bids'][0]['quantity'] == 100
    assert stock['asks'][0]['price'] == Decimal('100.05')
    assert stock['ltt'] == START
    assert stock['receipt_ts'] > stock['exchange_ts']
    for row in rows:
        assert row['session_date'] == START.astimezone(sim.ist).date()
        assert row['exchange_ts'].tzinfo is not None
    indices = [row for row in rows if row['symbol'] != 'TEST']
    assert {row['symbol'] for row in indices} == {'NIFTY_50', 'BANK_NIFTY', 'INDIA_VIX'}
    assert all(row['vtt'] is None and row['bids'] == [] for row in indices)


def test_trend_range_and_seed_determinism():
    _, _, frames, tables = decode_run('trend')
    prices = [table.to_pylist()[0]['ltp'] for table in tables]
    # Decoder sorts by instrument key; locate the stock explicitly.
    prices = [next(r['ltp'] for r in t.to_pylist() if r['symbol'] == 'TEST') for t in tables]
    assert prices[-1] > prices[0]
    _, _, range_frames, range_tables = decode_run('range', count=20)
    range_prices = [next(r['ltp'] for r in t.to_pylist() if r['symbol'] == 'TEST') for t in range_tables]
    assert max(range_prices) - min(range_prices) <= Decimal('0.50')
    assert frames == list(FeedSimulator(start=START, scenario='trend').frames(8))
    assert frames != range_frames[:8]


@pytest.mark.parametrize('scenario, flag', [
    ('gap', 'GAP'), ('reset', 'VOLUME_RESET'),
    ('duplicate', 'DUPLICATE'), ('out_of_order', 'OUT_OF_ORDER'),
])
def test_faults_preserved_and_counted(scenario, flag):
    _, decoder, frames, tables = decode_run(scenario)
    rows = [r for t in tables for r in t.to_pylist() if r['symbol'] == 'TEST']
    assert len(rows) == len(frames) # No silent drops or fills.
    assert any(flag in row['flags'] for row in rows)
    assert decoder.counters[flag] > 0


def test_stale_snapshot_does_not_make_next_normal_tick_a_reset():
    _, _, _, tables = decode_run('out_of_order')
    stocks = [next(r for r in t.to_pylist() if r['symbol'] == 'TEST') for t in tables]
    assert 'OUT_OF_ORDER' in stocks[3]['flags']
    assert 'VOLUME_RESET' not in stocks[4]['flags']


def test_truncation_and_symbol_isolation():
    sim = FeedSimulator(start=START, scenario='gap')
    frames = list(sim.frames(10))
    full = Decoder(sim.instruments, gap_seconds=2)
    short = Decoder(sim.instruments, gap_seconds=2)
    a = [full.decode(f).to_pylist() for f in frames]
    b = [short.decode(f).to_pylist() for f in frames[:5]]
    assert a[:5] == b


def test_disconnect_is_an_explicit_transport_event():
    sim = FeedSimulator(start=START, scenario='disconnect')
    iterator = sim.frames(8)
    for _ in range(3):
        next(iterator)
    with pytest.raises(SimulatedDisconnect):
        next(iterator)


@pytest.mark.parametrize('scenario,status', [('forbidden', 403), ('expired_token', 401)])
def test_auth_fault_simulator(scenario, status):
    service = SimulatedHTTP(scenario)
    response = service.request('GET', 'feed-authorize', headers={'User-Agent': 'orderflow-test'})
    assert response.status_code == status
    assert 'error' in response.json()
    assert len(service.calls) == 1


def test_http_simulator_enforces_user_agent_without_a_live_call():
    service = SimulatedHTTP()
    assert service.request('GET', 'feed-authorize', headers={}).status_code == 403
    response = service.request('GET', 'feed-authorize', headers={'User-Agent': 'orderflow-test'})
    assert response.status_code == 200
    assert response.json()['data']['authorized_redirect_uri'].startswith('simulator://')


def test_invalid_time_payload_and_instrument_are_explicit_errors():
    sim = FeedSimulator(start=START)
    frame = next(sim.frames(1))
    with pytest.raises(ValueError, match='aware'):
        FeedSimulator(start=START.replace(tzinfo=None))
    with pytest.raises(ValueError, match='aware'):
        Decoder(sim.instruments).decode(dict(frame, receipt_ts=START.replace(tzinfo=None)))
    with pytest.raises(DecodeError):
        Decoder(sim.instruments).decode(dict(frame, payload=b'\xff'))
    with pytest.raises(ValueError, match='instrument'):
        Decoder({}).decode(frame)


def test_candle_known_answer_and_availability():
    data = candle_response(START, 3)
    table = decode_candles(data, symbol='TEST', instrument_key='NSE_EQ|TEST',
                           receipt_ts=START + timedelta(minutes=4))
    assert table.schema.equals(CANDLE_SCHEMA, check_metadata=True)
    row = table.to_pylist()[0]
    assert row['open'] == Decimal('100')
    assert row['high'] == Decimal('100.20')
    assert row['low'] == Decimal('99.90')
    assert row['close'] == Decimal('100.10')
    assert row['volume'] == 1000
    assert row['available_at'] == START + timedelta(minutes=4)
    assert row['bar_end'] == START + timedelta(minutes=1)
    assert row['method'] == 'OBSERVED'
    assert table.num_rows == 3


def test_history_duplicates_gaps_and_out_of_order_are_preserved():
    response = candle_response(START, 5, scenario='gap_duplicate_out_of_order')
    table = decode_candles(response, symbol='TEST', instrument_key='NSE_EQ|TEST',
                           receipt_ts=START + timedelta(minutes=10))
    flags = {flag for r in table.to_pylist() for flag in r['flags']}
    assert {'GAP', 'DUPLICATE', 'OUT_OF_ORDER'} <= flags
    assert table.num_rows == len(response['data']['candles'])


def test_open_candle_and_invalid_ohlc_are_rejected():
    response = candle_response(START, 1)
    with pytest.raises(ValueError, match='closed'):
        decode_candles(response, symbol='TEST', instrument_key='NSE_EQ|TEST', receipt_ts=START)
    response['data']['candles'][0][2] = 90
    with pytest.raises(ValueError, match='OHLC'):
        decode_candles(response, symbol='TEST', instrument_key='NSE_EQ|TEST',
                       receipt_ts=START + timedelta(minutes=1))


def test_ltpc_and_greeks_mode_preserve_absent_fields():
    sim = FeedSimulator(start=START)
    frame = next(sim.frames(1))
    message = pb.FeedResponse(currentTs=int(START.timestamp() * 1000))
    message.feeds['NSE_EQ|TEST'].ltpc.CopyFrom(pb.LTPC(ltp=101, ltt=message.currentTs, ltq=7))
    row = Decoder(sim.instruments).decode(dict(frame, payload=message.SerializeToString())).to_pylist()[0]
    assert row['ltp'] == Decimal('101')
    assert row['vtt'] is None and row['bids'] == []
    message.ClearField('feeds')
    first = message.feeds['NSE_EQ|TEST'].firstLevelWithGreeks
    first.ltpc.ltp = 101
    first.ltpc.ltt = message.currentTs
    first.vtt = 99
    first.firstDepth.bidP = 100.95
    first.firstDepth.bidQ = 10
    first.firstDepth.askP = 101.05
    first.firstDepth.askQ = 20
    row = Decoder(sim.instruments).decode(dict(frame, payload=message.SerializeToString())).to_pylist()[0]
    assert row['vtt'] == 99
    assert len(row['bids']) == 1
    assert row['tbq'] is None and row['tsq'] is None


def test_session_reset_is_first_tick_not_volume_reset():
    sim = FeedSimulator(start=START)
    frame = next(sim.frames(1))
    decoder = Decoder(sim.instruments)
    decoder.decode(frame)
    tomorrow = next(FeedSimulator(start=START + timedelta(days=1), scenario='reset').frames(1))
    rows = decoder.decode(tomorrow).to_pylist()
    assert all('FIRST_TICK' in r['flags'] and 'VOLUME_RESET' not in r['flags'] for r in rows)


def test_candle_truncation_does_not_change_earlier_values():
    response = candle_response(START, 10)
    cutoff = START + timedelta(minutes=10)
    full = decode_candles(response, symbol='TEST', instrument_key='NSE_EQ|TEST', receipt_ts=cutoff)
    short_response = {'status': 'success', 'data': {'candles': response['data']['candles'][:5]}}
    short = decode_candles(short_response, symbol='TEST', instrument_key='NSE_EQ|TEST', receipt_ts=cutoff)
    assert full.slice(0, 5).equals(short)
