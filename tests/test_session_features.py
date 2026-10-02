"""Regular-session features must ignore flagged audit-only trade phases."""
from datetime import timedelta
from decimal import Decimal as D
import pyarrow as pa
from orderflow.schema import TRADE_SCHEMA
from orderflow.trades.core import classify_ticks
from orderflow.bars.core import time_bars
from orderflow.layers.orderflow.footprint import footprint
from orderflow.layers.orderflow.flow import vpin
from orderflow.layers.profile.core import session_profile
from orderflow.layers.vwap.core import vwap_features
from test_trades_bars import START,ticks


def test_audit_phases_cannot_enter_regular_profile_vwap_footprint_or_vpin():
    regular=classify_ticks(ticks([(100,0,99,101,[]),(101,10,99,101,[]),(99,30,99,101,[])]))
    seed=regular.to_pylist()[0]
    pre=dict(seed,sequence=5000,price=D(500),volume=1,side='BUY',
        exchange_ts=START-timedelta(minutes=10),receipt_ts=START-timedelta(minutes=10),
        available_at=START-timedelta(minutes=10),flags=['OUTSIDE_SESSION'],inputs=[])
    post=dict(seed,sequence=5001,price=D(800),volume=2,side='BUY',
        exchange_ts=START+timedelta(hours=7),receipt_ts=START+timedelta(hours=7),
        available_at=START+timedelta(hours=7),flags=['OUTSIDE_SESSION'],inputs=[])
    audit=pa.concat_tables([pa.Table.from_pylist([pre],schema=TRADE_SCHEMA),regular,
        pa.Table.from_pylist([post],schema=TRADE_SCHEMA)])
    cutoff=START+timedelta(hours=8)
    bars=time_bars(regular,minutes=1,as_of=cutoff)
    assert footprint(audit,bars,tick_size=D('.05')).equals(footprint(regular,bars,tick_size=D('.05')))
    assert session_profile(audit,tick_size=D('.05'),as_of=cutoff).equals(session_profile(regular,tick_size=D('.05'),as_of=cutoff))
    assert vwap_features(audit,as_of=cutoff).equals(vwap_features(regular,as_of=cutoff))
    assert vpin(audit,bucket_size=20,as_of=cutoff).equals(vpin(regular,bucket_size=20,as_of=cutoff))


def test_historical_profile_and_vwap_filter_unflagged_pre_and_post_candles():
    from orderflow.schema import CANDLE_SCHEMA
    seed=dict(symbol='X',instrument_key='NSE_EQ|X',session_date=START.date(),
        bar_start=START,bar_end=START+timedelta(minutes=1),timeframe_minutes=1,
        open=D(100),high=D(102),low=D(100),close=D(101),volume=10,oi=None,
        source='history',method='APPROXIMATE',confidence='LOW',flags=[],
        available_at=START+timedelta(minutes=1),inputs=[])
    pre=dict(seed,bar_start=START-timedelta(minutes=10),bar_end=START-timedelta(minutes=9),
        open=D(500),high=D(500),low=D(500),close=D(500),volume=1)
    post=dict(seed,bar_start=START+timedelta(hours=7),bar_end=START+timedelta(hours=7,minutes=1),
        open=D(800),high=D(800),low=D(800),close=D(800),volume=2,
        available_at=START+timedelta(hours=7,minutes=1))
    regular=pa.Table.from_pylist([seed],schema=CANDLE_SCHEMA)
    audit=pa.Table.from_pylist([pre,seed,post],schema=CANDLE_SCHEMA)
    cutoff=START+timedelta(hours=8)
    assert session_profile(audit,tick_size=D('.05'),as_of=cutoff).equals(session_profile(regular,tick_size=D('.05'),as_of=cutoff))
    assert vwap_features(audit,as_of=cutoff).equals(vwap_features(regular,as_of=cutoff))


def test_feature_clock_parameters_apply_to_live_trades_too():
    from datetime import time
    regular=classify_ticks(ticks([(100,0,99,101,[]),(101,10,99,101,[])]))
    kwargs=dict(as_of=START+timedelta(hours=8),session_open=time(10),session_close=time(11))
    assert session_profile(regular,tick_size=D('.05'),**kwargs).num_rows==0
    assert vwap_features(regular,**kwargs).num_rows==0
