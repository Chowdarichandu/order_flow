"""T08 exact flow answers, confirmation timing and truncation."""
from datetime import timedelta
from decimal import Decimal as D
import math
import pyarrow as pa
import pytest
from test_trades_bars import START
from orderflow.schema import BAR_SCHEMA,TRADE_SCHEMA,FOOTPRINT_SCHEMA
from orderflow.layers.orderflow.flow import vpin,kyle_lambda,flow_events


def bars(spec):
    rows=[]
    for i,(high,low,delta,cvd,mid) in enumerate(spec):
        start=START+timedelta(minutes=i);end=start+timedelta(minutes=1)
        rows.append(dict(symbol='TEST',instrument_key='NSE_EQ|TEST',session_date=START.date(),bar_id=f'b{i}',bar_kind='TIME',
            bar_start=start,bar_end=end,timeframe_minutes=1,volume_target=None,open=D(str(low)),high=D(str(high)),low=D(str(low)),
            close=D(str(mid)),mid_close=D(str(mid)),volume=abs(delta),buy_volume=max(delta,0),sell_volume=max(-delta,0),unknown_volume=0,
            delta=delta,cvd=cvd,source='SIMULATOR',method='ESTIMATE',confidence='LOW',flags=[],available_at=end,inputs=[]))
    return pa.Table.from_pylist(rows,schema=BAR_SCHEMA)


def trades(spec):
    rows=[]
    for i,(volume,side) in enumerate(spec):
        ts=START+timedelta(seconds=i)
        rows.append(dict(symbol='TEST',instrument_key='NSE_EQ|TEST',session_date=START.date(),sequence=i,exchange_ts=ts,
            receipt_ts=ts,price=D('100'),mid_price=D('100'),volume=volume,side=side,quote_ts=None,source='SIMULATOR',method='ESTIMATE',
            confidence='LOW',flags=[],available_at=ts,inputs=[]))
    return pa.Table.from_pylist(rows,schema=TRADE_SCHEMA)


def events(data,**kwargs):
    return flow_events(data,pa.Table.from_pylist([],schema=FOOTPRINT_SCHEMA),tick_size=D('1'),dominant_fraction=.6,
                       as_of=START+timedelta(minutes=100),extreme_bars=3,confirmation_bars=2,swing_bars_each_side=1,**kwargs).to_pylist()


def test_vpin_exact_unknown_split_and_buckets_cross_snapshot():
    data=trades([(15,'BUY'),(5,'UNKNOWN'),(10,'SELL')])
    out=vpin(data,bucket_size=10,rolling_buckets=2,as_of=START+timedelta(minutes=1)).to_pylist()
    assert [r['value'] for r in out]==[1,.75,.75]
    assert [r['unknown_share'] for r in out]==[0,.25,.25]
    assert [r['n'] for r in out]==[1,2,2]
    assert all(r['method']=='ESTIMATE' for r in out)
    assert out[1]['available_at']==START+timedelta(seconds=1)


def test_vpin_partial_bucket_not_emitted_day_resets_and_truncation():
    data=trades([(4,'UNKNOWN'),(6,'BUY'),(100,'SELL')]);cutoff=START+timedelta(seconds=1)
    assert vpin(data,bucket_size=10,as_of=cutoff).equals(vpin(data.slice(0,2),bucket_size=10,as_of=cutoff))
    assert vpin(data.slice(0,1),bucket_size=10,as_of=cutoff).num_rows==0
    rows=data.slice(0,2).to_pylist();rows[1]['session_date']+=timedelta(days=1)
    assert vpin(pa.Table.from_pylist(rows,schema=TRADE_SCHEMA),bucket_size=10,as_of=cutoff).num_rows==0


def test_vpin_requires_fixed_positive_bucket_and_preserves_quality():
    with pytest.raises(ValueError):vpin(trades([]),bucket_size=0,as_of=START)
    data=trades([(10,'BUY'),(10,'SELL')]).to_pylist();data[1]['flags']=['DUPLICATE']
    out=vpin(pa.Table.from_pylist(data,schema=TRADE_SCHEMA),bucket_size=10,as_of=START+timedelta(minutes=1)).to_pylist()
    assert len(out)==1


def test_kyle_known_ols_return_and_constant_regressor():
    data=bars([(100,100,0,0,100),(101,100,1,1,101),(103.02,101,2,3,103.02),(106.1106,103.02,3,6,106.1106)])
    out=kyle_lambda(data,as_of=START+timedelta(minutes=4),return_definition='simple',window_minutes=30).to_pylist()[-1]
    assert out['value']==pytest.approx(.01) and out['r_squared']==pytest.approx(1) and out['n']==3
    constant=bars([(101,99,5,5,100),(101,99,5,10,101),(103,99,5,15,102)])
    row=kyle_lambda(constant,as_of=START+timedelta(minutes=3),return_definition='simple').to_pylist()[-1]
    assert row['value'] is None and row['r_squared'] is None and 'ZERO_DELTA_VARIANCE' in row['flags']


def test_kyle_truncation_gap_and_explicit_return_definition():
    data=bars([(100+i,99, i,i,100+i) for i in range(6)]);cutoff=START+timedelta(minutes=3)
    assert kyle_lambda(data,as_of=cutoff,return_definition='log').equals(kyle_lambda(data.slice(0,3),as_of=cutoff,return_definition='log'))
    with pytest.raises(ValueError):kyle_lambda(data,as_of=cutoff,return_definition='invented')
    rows=data.to_pylist();rows[2]['bar_start']+=timedelta(minutes=1);rows[2]['bar_end']+=timedelta(minutes=1);rows[2]['available_at']=rows[2]['bar_end']
    result=kyle_lambda(pa.Table.from_pylist(rows[:3],schema=BAR_SCHEMA),as_of=START+timedelta(minutes=4),return_definition='simple').to_pylist()[-1]
    assert result['n']==1 and 'GAP' in result['flags']


def test_exhaustion_no_extension_and_confirm_only_after_M_closes():
    data=bars([(100,98,5,5,99),(101,99,8,13,100),(102,100,10,23,101),(105,103,100,123,104),(104,102,5,128,103),(105,102,4,132,103)])
    full=events(data)
    ex=[e for e in full if e['event_type']=='EXHAUSTION' and e['price']==D('105')]
    assert len(ex)==1 and ex[0]['side']=='SELL' and ex[0]['available_at']==START+timedelta(minutes=6)
    early=flow_events(data,pa.Table.from_pylist([],schema=FOOTPRINT_SCHEMA),tick_size=D('1'),dominant_fraction=.6,
        as_of=START+timedelta(minutes=5),extreme_bars=3,confirmation_bars=2,swing_bars_each_side=1).to_pylist()
    assert not [e for e in early if e['event_type']=='EXHAUSTION' and e['price']==D('105')]
    assert flow_events(data,pa.Table.from_pylist([],schema=FOOTPRINT_SCHEMA),tick_size=D('1'),dominant_fraction=.6,
        as_of=START+timedelta(minutes=5),extreme_bars=3,confirmation_bars=2,swing_bars_each_side=1).equals(
        flow_events(data.slice(0,5),pa.Table.from_pylist([],schema=FOOTPRINT_SCHEMA),tick_size=D('1'),dominant_fraction=.6,
        as_of=START+timedelta(minutes=5),extreme_bars=3,confirmation_bars=2,swing_bars_each_side=1))


def test_exhaustion_extension_invalidates_and_percentile_uses_candidate_past():
    data=bars([(100,98,5,5,99),(101,99,8,13,100),(102,100,10,23,101),(105,103,100,123,104),(106,102,1000,1123,103),(104,102,4,1127,103)])
    assert not [e for e in events(data) if e['event_type']=='EXHAUSTION' and e['price']==D('105')]


def test_divergence_confirmed_swings_higher_price_lower_cvd():
    data=bars([(100,97,1,10,99),(103,98,1,30,102),(101,99,1,20,100),(105,100,1,25,104),(102,99,1,20,101)])
    out=[e for e in events(data) if e['event_type']=='DELTA_DIVERGENCE']
    assert len(out)==1 and out[0]['side']=='SELL' and out[0]['price']==D('105')
    assert out[0]['available_at']==START+timedelta(minutes=5)
    assert not [e for e in events(data.slice(0,4)) if e['event_type']=='DELTA_DIVERGENCE']


def test_absorption_known_answer_requires_into_level_and_bounded_extension():
    data=bars([(102,99,0,0,100)]*3);rows=[]
    for bar in data.to_pylist():
        for price,bid,ask in [(100,100,5),(101,0,1),(102,0,1),(103,0,1)]:
            rows.append(dict(symbol=bar['symbol'],instrument_key=bar['instrument_key'],session_date=bar['session_date'],bar_id=bar['bar_id'],
                price=D(price),bid_volume=bid,ask_volume=ask,unknown_volume=0,buy_imbalance=False,sell_imbalance=False,stacked_buy=False,stacked_sell=False,
                source='SIMULATOR',method='ESTIMATE',confidence='LOW',flags=[],available_at=bar['available_at'],inputs=[]))
    fp=pa.Table.from_pylist(rows,schema=FOOTPRINT_SCHEMA)
    out=flow_events(data,fp,tick_size=D('1'),dominant_fraction=.6,as_of=START+timedelta(minutes=3)).to_pylist()
    assert [r for r in out if r['event_type']=='ABSORPTION' and r['price']==D('100') and r['side']=='BUY']
    # Sellers dominate into support; a move more than 2 ticks below the level invalidates it.
    b=data.to_pylist();b[-1]['low']=D('97')
    out=flow_events(pa.Table.from_pylist(b,schema=BAR_SCHEMA),fp,tick_size=D('1'),dominant_fraction=.6,as_of=START+timedelta(minutes=3)).to_pylist()
    assert not [r for r in out if r['event_type']=='ABSORPTION' and r['price']==D('100') and r['side']=='BUY']


def test_absorption_late_footprint_cannot_change_past_event():
    data=bars([(102,99,0,0,100)]*3)
    template=dict(symbol='TEST',instrument_key='NSE_EQ|TEST',session_date=START.date(),bar_id='b0',price=D(100),bid_volume=1000,ask_volume=0,
        unknown_volume=0,buy_imbalance=False,sell_imbalance=False,stacked_buy=False,stacked_sell=False,source='SIMULATOR',method='ESTIMATE',confidence='LOW',
        flags=[],available_at=START+timedelta(minutes=10),inputs=[])
    fp=pa.Table.from_pylist([template],schema=FOOTPRINT_SCHEMA);empty=pa.Table.from_pylist([],schema=FOOTPRINT_SCHEMA)
    kwargs=dict(tick_size=D('1'),dominant_fraction=.6,as_of=START+timedelta(minutes=3))
    assert flow_events(data,fp,**kwargs).equals(flow_events(data,empty,**kwargs))


def test_vpin_fractional_fixed_bucket_and_missing_bucket_validation():
    data=trades([(5,'BUY')])
    out=vpin(data,bucket_size=2.5,as_of=START).to_pylist()
    assert len(out)==2 and [r['value'] for r in out]==[1,1]
    with pytest.raises(ValueError):vpin(data,bucket_size=float('nan'),as_of=START)
    sizes={('NSE_EQ|TEST',START.date()):D('2.5')}
    assert vpin(data,bucket_size=sizes,as_of=START).equals(vpin(data,bucket_size=2.5,as_of=START))
    with pytest.raises(ValueError):vpin(data,bucket_size={},as_of=START)


def test_bullish_divergence_and_tied_extreme_is_not_swing():
    data=bars([(104,100,-1,20,102),(103,97,-1,5,99),(104,99,-1,10,102),(103,95,-1,8,99),(104,99,-1,10,102)])
    out=[e for e in events(data) if e['event_type']=='DELTA_DIVERGENCE']
    assert len(out)==1 and out[0]['side']=='BUY' and out[0]['price']==D('95')
    rows=data.to_pylist();rows[-1]['low']=D('95')
    assert not [e for e in events(pa.Table.from_pylist(rows,schema=BAR_SCHEMA)) if e['event_type']=='DELTA_DIVERGENCE']


def test_kyle_missing_mid_and_rolling_window_no_fake_observations():
    data=bars([(100+i,99,i,i,100+i) for i in range(6)])
    rows=data.to_pylist();rows[3]['mid_close']=None
    out=kyle_lambda(pa.Table.from_pylist(rows,schema=BAR_SCHEMA),as_of=START+timedelta(minutes=6),return_definition='simple',window_minutes=2).to_pylist()[-1]
    assert out['n']==1 and out['value'] is None and 'MISSING_MID' in out['flags']


def test_all_events_input_availability_and_full_truncation():
    data=bars([(100+i%3,98-i%3,30+i,20-i,99) for i in range(12)])
    empty=pa.Table.from_pylist([],schema=FOOTPRINT_SCHEMA)
    kwargs=dict(tick_size=D('1'),dominant_fraction=.6,extreme_bars=3,confirmation_bars=2,swing_bars_each_side=1)
    for n in range(1,13):
        cutoff=START+timedelta(minutes=n)
        full=flow_events(data,empty,as_of=cutoff,**kwargs)
        assert full.equals(flow_events(data.slice(0,n),empty,as_of=cutoff,**kwargs))
        assert all(ref['available_at']<=row['available_at'] for row in full.to_pylist() for ref in row['inputs'])


def test_unknown_only_vpin_zero_imbalance_and_full_unknown_share():
    row=vpin(trades([(10,'UNKNOWN')]),bucket_size=10,as_of=START).to_pylist()[0]
    assert row['value']==0 and row['unknown_share']==1


def test_bullish_exhaustion_only_after_confirming_bars_close():
    data=bars([(103,101,-5,-5,102),(102,100,-8,-13,101),(101,99,-10,-23,100),
               (98,95,-100,-123,97),(99,96,-5,-128,98),(99,95,-4,-132,98)])
    out=[e for e in events(data) if e['event_type']=='EXHAUSTION' and e['price']==D('95')]
    assert len(out)==1 and out[0]['side']=='BUY' and out[0]['confirmed_at']==START+timedelta(minutes=6)


def history_sessions(count=20):
    """Complete regular-session one-minute candles from preceding weekdays."""
    from orderflow.schema import CANDLE_SCHEMA
    dates=[];day=START.date()-timedelta(days=1)
    while len(dates)<count:
        if day.weekday()<5:dates.append(day)
        day-=timedelta(days=1)
    rows=[]
    for i,day in enumerate(reversed(dates)):
        opening=START.replace(year=day.year,month=day.month,day=day.day)
        for minute in range(375):
            begin=opening+timedelta(minutes=minute);end=begin+timedelta(minutes=1)
            rows.append(dict(symbol='TEST',instrument_key='NSE_EQ|TEST',session_date=day,bar_start=begin,bar_end=end,timeframe_minutes=1,
                open=D(100),high=D(101),low=D(99),close=D(100),volume=i+1,oi=None,source='history',method='EXACT',confidence='HIGH',flags=[],
                available_at=end,inputs=[]))
    return pa.Table.from_pylist(rows,schema=CANDLE_SCHEMA)


def test_vpin_bucket_parameters_exact_fractional_twenty_day_average():
    from orderflow.layers.orderflow.flow import vpin_bucket_parameters
    data=history_sessions();out=vpin_bucket_parameters(data,for_session=START.date(),as_of=START)
    assert out.schema.equals(__import__('orderflow.schema',fromlist=['FEATURE_SCHEMA']).FEATURE_SCHEMA)
    row=out.to_pylist()[0]
    assert row['value']==78.75 and row['n']==20 and row['name']=='VPIN_BUCKET_SIZE'
    assert row['session_date']==START.date() and row['available_at']==START
    assert all(ref['available_at']<=START for ref in row['inputs'])


def test_vpin_bucket_parameters_missing_incomplete_and_late_history_are_null():
    from orderflow.layers.orderflow.flow import vpin_bucket_parameters
    data=history_sessions()
    short=vpin_bucket_parameters(data.slice(0,19*375),for_session=START.date(),as_of=START).to_pylist()[0]
    assert short['value'] is None and short['n']==19 and 'INSUFFICIENT_DAILY_HISTORY' in short['flags']
    incomplete=vpin_bucket_parameters(data.slice(0,data.num_rows-1),for_session=START.date(),as_of=START).to_pylist()[0]
    assert incomplete['value'] is None and 'INCOMPLETE_SESSION' in incomplete['flags']
    rows=data.to_pylist();rows[-1]['available_at']=START+timedelta(seconds=1)
    late=vpin_bucket_parameters(pa.Table.from_pylist(rows,schema=data.schema),for_session=START.date(),as_of=START).to_pylist()[0]
    assert late['value'] is None and late['n']==19 and 'INCOMPLETE_SESSION' in late['flags']


def test_vpin_bucket_parameters_no_current_day_and_truncation():
    from orderflow.layers.orderflow.flow import vpin_bucket_parameters
    data=history_sessions();today=history_sessions(1).to_pylist()
    for row in today:
        row['session_date']=START.date();row['bar_start']+=timedelta(days=1);row['bar_end']+=timedelta(days=1);row['available_at']=row['bar_end'];row['volume']=100000
    full=pa.concat_tables([data,pa.Table.from_pylist(today,schema=data.schema)])
    assert vpin_bucket_parameters(full,for_session=START.date(),as_of=START).equals(vpin_bucket_parameters(data,for_session=START.date(),as_of=START))
    with pytest.raises(ValueError):vpin_bucket_parameters(data,for_session=START.date(),as_of=START+timedelta(seconds=1))


def test_vpin_bucket_parameters_duplicate_and_gap_flags_preserve_totals():
    from orderflow.layers.orderflow.flow import vpin_bucket_parameters
    data=history_sessions();duplicate=pa.concat_tables([data,data.slice(0,1)])
    row=vpin_bucket_parameters(duplicate,for_session=START.date(),as_of=START).to_pylist()[0]
    assert row['value']==78.75 and 'DUPLICATE_CANDLE' in row['flags']


def test_vpin_bucket_parameters_observed_session_gap_is_flagged_not_filled():
    from orderflow.layers.orderflow.flow import vpin_bucket_parameters
    data=history_sessions(21)
    # Remove an entire weekday; no holiday assumption or zero-filled daily total.
    short=pa.concat_tables([data.slice(0,5*375),data.slice(6*375)])
    row=vpin_bucket_parameters(short,for_session=START.date(),as_of=START).to_pylist()[0]
    assert row['n']==20 and row['value'] is not None and 'UNVERIFIED_SESSION_GAP' in row['flags']
    expected=sum(i for i in range(1,22) if i!=6)*375/20/50
    assert row['value']==expected
