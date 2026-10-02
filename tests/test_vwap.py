"""T10 weighted population bands, anchors and VWAP event timing."""
from datetime import timedelta
from decimal import Decimal as D
import math
import pyarrow as pa
from orderflow.layers.vwap.core import weighted_vwap,vwap_features,vwap_events
from orderflow.trades.core import classify_ticks
from test_trades_bars import START,ticks


def test_weighted_vwap_population_variance_known_answer():
    value=weighted_vwap([(D('100'),1),(D('102'),3)])
    assert value['vwap']==101.5 and abs(value['sigma']-math.sqrt(.75))<1e-12
    assert weighted_vwap([(D('100'),0)])=={'vwap':None,'sigma':None}


def test_anchored_vwap_not_available_before_swing_confirmation():
    data=classify_ticks(ticks([(100,0,99,101,[]),(101,10,99,101,[]),(102,20,99,101,[])]))
    anchor={'id':'swing','origin_at':START,'available_at':START+timedelta(seconds=25)}
    early=vwap_features(data,as_of=START+timedelta(seconds=24),anchors=[anchor]).to_pylist()
    late=vwap_features(data,as_of=START+timedelta(seconds=30),anchors=[anchor]).to_pylist()
    assert not any(r['name'].startswith('ANCHOR_swing') for r in early)
    assert any(r['name']=='ANCHOR_swing_VWAP' and r['value']==101.5 for r in late)


def test_vwap_truncation_week_month_and_session():
    data=classify_ticks(ticks([(100,0,99,101,[]),(101,10,99,101,[]),(102,20,99,101,[]),(103,30,99,101,[])]))
    cutoff=START+timedelta(seconds=25)
    assert vwap_features(data,as_of=cutoff).equals(vwap_features(data.slice(0,3),as_of=cutoff))
    names={r['name'] for r in vwap_features(data,as_of=cutoff).to_pylist()}
    assert {'SESSION_VWAP','WEEK_VWAP','MONTH_VWAP','SESSION_BAND_UP_2'}<=names


def test_reclaim_rejection_tags_and_acceptance_require_closed_bars():
    # Scalar event detector assumes these rows already joined to point-in-time VWAP values.
    rows=[dict(close=D(str(p)),low=D(str(p-1)),high=D(str(p+1)),vwap=100,
               sigma=1,available_at=START+timedelta(minutes=i+1)) for i,p in enumerate([98,99,101,103,104,105])]
    early=vwap_events(rows,as_of=START+timedelta(minutes=5))
    late=vwap_events(rows,as_of=START+timedelta(minutes=6))
    assert any(e['type']=='VWAP_RECLAIM' and e['available_at']==START+timedelta(minutes=3) for e in early)
    assert any(e['type']=='VWAP_REJECTION' for e in early)
    assert any(e['type']=='BAND_TAG' for e in early)
    assert not any(e['type']=='BAND_ACCEPTANCE' for e in early)
    assert any(e['type']=='BAND_ACCEPTANCE' and e['sigma_multiple']==2 for e in late)


def test_historical_typical_price_is_approximate_and_zero_volume_is_null():
    from orderflow.schema import CANDLE_SCHEMA
    source=dict(symbol='X',instrument_key='NSE_EQ|X',session_date=START.date(),
        bar_start=START,bar_end=START+timedelta(minutes=1),timeframe_minutes=1,
        open=D(99),high=D(103),low=D(99),close=D(101),volume=10,oi=None,
        source='history',method='EXACT',confidence='HIGH',flags=[],
        available_at=START+timedelta(minutes=1),inputs=[])
    result=vwap_features(pa.Table.from_pylist([source],schema=CANDLE_SCHEMA),as_of=source['available_at']).to_pylist()
    assert next(r for r in result if r['name']=='SESSION_VWAP')['value']==101
    assert all(r['method']=='APPROXIMATE' for r in result)
    source['volume']=0
    result=vwap_features(pa.Table.from_pylist([source],schema=CANDLE_SCHEMA),as_of=source['available_at']).to_pylist()
    assert all(r['value'] is None and r['flags']==['ZERO_VOLUME'] for r in result)


def test_event_join_with_later_vwap_availability_is_gated():
    row=dict(close=D(101),low=D(99),high=D(102),vwap=100,sigma=1,
        available_at=START+timedelta(minutes=1),vwap_available_at=START+timedelta(minutes=2))
    assert vwap_events([row],as_of=START+timedelta(minutes=1))==[]
    assert all(e['available_at']==row['vwap_available_at'] for e in vwap_events([row],as_of=row['vwap_available_at']))
