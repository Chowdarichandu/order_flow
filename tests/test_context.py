"""T13 exact context arithmetic, configured policies and causal truncation."""
from datetime import timedelta, time
from decimal import Decimal as D
import pyarrow as pa
import pytest
from test_trades_bars import START,ticks
from orderflow.schema import BAR_SCHEMA,FEATURE_SCHEMA,TICK_SCHEMA,LEVEL_SCHEMA,EVENT_SCHEMA,CONTEXT_SCHEMA
from orderflow.trades.core import classify_ticks
from orderflow.bars.core import time_bars
from orderflow.layers.context.core import relative_strength,percentile_rank,vix_regime,time_category,liquidity_tier,index_regime,context_snapshot

BOUNDARIES={'MORNING':(time(9,45),time(11)), 'MIDDAY':(time(11),time(13)), 'AFTERNOON':(time(13),time(14,45))}


def test_sector_return_difference_is_fractional_return():
    assert relative_strength(110,100,105,100)==pytest.approx(.05)
    assert relative_strength(90,100,95,100)==pytest.approx(-.05)
    assert relative_strength(100,0,100,100) is None


def test_vix_rank_and_regime_explicit_thresholds():
    assert percentile_rank(20,[10,20,20,30],method='weak')==75
    assert percentile_rank(20,[10,20,20,30],method='mean')==50
    assert vix_regime(75,low=25,high=70)=='HIGH'
    assert vix_regime(10,low=25,high=70)=='LOW'
    assert vix_regime(50,low=25,high=70)=='NORMAL'
    with pytest.raises(ValueError):vix_regime(50,low=80,high=20)


def test_time_boundaries_ist_and_missing_middle_parameters_rejected():
    assert time_category(START,boundaries=BOUNDARIES)=='OPEN'
    assert time_category(START+timedelta(minutes=30),boundaries=BOUNDARIES)=='MORNING'
    assert time_category(START+timedelta(hours=5,minutes=30),boundaries=BOUNDARIES)=='CLOSE'
    assert time_category(START+timedelta(hours=6),boundaries=BOUNDARIES)=='OUTSIDE_SESSION'
    with pytest.raises(ValueError):time_category(START,boundaries={})


def test_liquidity_explicit_thresholds_and_worst_dimension():
    args=dict(value_thresholds=(100,1000),spread_thresholds=(.01,.05))
    assert liquidity_tier(2000,.005,**args)==1
    assert liquidity_tier(500,.02,**args)==2
    assert liquidity_tier(2000,.1,**args)==3
    assert liquidity_tier(None,.01,**args) is None


def test_index_consensus_policy_is_required_and_position_matters():
    assert index_regime([('UP',110,100),('UP',210,200)],policy='unanimous')=='TREND_UP'
    assert index_regime([('DOWN',90,100),('DOWN',190,200)],policy='unanimous')=='TREND_DOWN'
    assert index_regime([('UP',110,100),('DOWN',190,200)],policy='unanimous')=='RANGE'
    assert index_regime([('UP',110,None)],policy='unanimous') is None


def feature(symbol,value,at):
    return dict(symbol=symbol,instrument_key='NSE_EQ|'+symbol,session_date=at.date(),minute=at,name='SESSION_VWAP',level=None,value=value,r_squared=None,n=None,unknown_share=None,window_start=None,window_end=None,source='SIMULATOR',method='ESTIMATE',confidence='LOW',flags=[],available_at=at,inputs=[])


def snapshot(bars,features,at,**extra):
    return context_snapshot(bars,features,pa.Table.from_pylist([],schema=TICK_SCHEMA),pa.Table.from_pylist([],schema=LEVEL_SCHEMA),pa.Table.from_pylist([],schema=EVENT_SCHEMA),as_of=at,sector_map={'TEST':'SECTOR'},index_symbols=('NIFTY_50','BANK_NIFTY'),vix_symbol='VIX',vix_percentile_method='weak',vix_thresholds=(25,75),time_boundaries=BOUNDARIES,value_thresholds=(100,1000),spread_thresholds=(.01,.05),index_policy='unanimous',advancer_basis='session_open',**extra)


def test_context_schema_breadth_relative_strength_and_future_truncation():
    bars=time_bars(classify_ticks(ticks([(100,0,99,101,[]),(110,10,99,101,[])])),minutes=1,as_of=START+timedelta(minutes=1))
    row=bars.to_pylist()[0];sector=dict(row,symbol='SECTOR',instrument_key='IDX|SECTOR',open=D('100'),close=D('105'),bar_id='sector')
    sector['available_at']=START+timedelta(minutes=1)
    table=pa.Table.from_pylist([row,sector],schema=BAR_SCHEMA)
    at=START+timedelta(minutes=1)
    values=pa.Table.from_pylist([feature('TEST',105,at),feature('SECTOR',104,at)],schema=FEATURE_SCHEMA)
    future=dict(row,bar_id='future',close=D('999'),available_at=at+timedelta(minutes=1),bar_end=at+timedelta(minutes=1))
    full=snapshot(pa.concat_tables([table,pa.Table.from_pylist([future],schema=BAR_SCHEMA)]),values,at,universe=('TEST',))
    short=snapshot(table,values,at,universe=('TEST',))
    assert full.equals(short) and full.schema.equals(CONTEXT_SCHEMA)
    out=full.to_pylist()[0]
    assert out['sector_rs_open']==pytest.approx(.05)
    assert out['breadth_above_vwap_fraction']==1 and out['advancers']==1 and out['decliners']==0
    assert 'VIX_HISTORY_MISSING' in out['flags']
    assert all(ref['available_at']<=out['available_at'] for ref in out['inputs'])


def test_unavailable_vwap_excluded_and_flat_stocks_not_advancers():
    bars=time_bars(classify_ticks(ticks([(100,0,99,101,[]),(100,10,99,101,[])])),minutes=1,as_of=START+timedelta(minutes=1))
    at=START+timedelta(minutes=1)
    values=pa.Table.from_pylist([feature('TEST',90,at+timedelta(seconds=1))],schema=FEATURE_SCHEMA)
    out=snapshot(bars,values,at,universe=('TEST',)).to_pylist()[0]
    assert out['breadth_above_vwap_fraction'] is None and out['advancers']==out['decliners']==0
    assert 'BREADTH_VWAP_MISSING' in out['flags']


def test_canonical_historical_vix_rs_liquidity_and_announcements():
    at=START+timedelta(minutes=1)
    prototype=time_bars(classify_ticks(ticks([(100,0,99,101,[]),(110,10,99,101,[])])),minutes=1,as_of=at).to_pylist()[0]
    bars=[];quote_rows=[]
    for i in range(21):
        date=(START-timedelta(days=20-i)).date();stamp=START-timedelta(days=20-i)
        for symbol,close in [('TEST',110 if i==20 else 100),('SECTOR',105 if i==20 else 100),('NIFTY_50',110),('BANK_NIFTY',110)]:
            bars.append(dict(prototype,symbol=symbol,instrument_key='KEY|'+symbol,session_date=date,bar_id=f'{symbol}-{date}',bar_start=stamp,bar_end=stamp+timedelta(minutes=1),available_at=stamp+timedelta(minutes=1),open=D('100'),close=D(str(close)),high=D('110'),low=D('100'),volume=20))
        q=ticks([(100,10,99.9,100.1,[])]).to_pylist()[0]
        quote_rows.append(dict(q,session_date=date,sequence=i,exchange_ts=stamp,receipt_ts=stamp,ltt=stamp))
    for i,value in enumerate([10,20,30]):
        stamp=START-timedelta(days=i+1);q=dict(quote_rows[0],symbol='VIX',instrument_key='IDX|VIX',sequence=100+i,session_date=stamp.date(),ltp=D(str(value)),exchange_ts=stamp,receipt_ts=stamp,ltt=stamp);quote_rows.append(q)
    quote_rows.append(dict(quote_rows[-1],session_date=START.date(),ltp=D('25'),exchange_ts=START,receipt_ts=START,ltt=START))
    old=START-timedelta(days=400);quote_rows.append(dict(quote_rows[-1],session_date=old.date(),ltp=D('1000'),exchange_ts=old,receipt_ts=old,ltt=old))
    levels=[]
    for symbol in ['NIFTY_50','BANK_NIFTY']:
        levels.append(dict(symbol=symbol,instrument_key='IDX|'+symbol,session_date=START.date(),record_id=symbol+'-bos',type='BOS',timeframe_minutes=15,low=D('100'),high=D('100'),side='BUY',origin_at=START,created_at=START,invalidated_at=None,mitigated_at=None,state='ACTIVE',source='SIM',method='ESTIMATE',confidence='LOW',flags=[],available_at=START,inputs=[]))
    announcements=[]
    for index,minutes,available in [(1,-30,at),(2,-61,at),(3,-10,at+timedelta(minutes=1))]:
        occurred=at+timedelta(minutes=minutes)
        announcements.append(dict(symbol='TEST',instrument_key='KEY|TEST',session_date=START.date(),event_id=str(index),event_type='announcement',occurred_at=occurred,confirmed_at=occurred,price=D('100'),side='UNKNOWN',strength=None,zone_id=None,source='SIM',method='OBSERVED',confidence='HIGH',flags=[],available_at=available,inputs=[]))
    # Supply complete prior-session stock bars for daily traded-value medians.
    originals=list(bars)
    for r in originals:
        if r['symbol']=='TEST' and r['session_date']<START.date():
            for minute in range(1,375):
                stamp=r['bar_start']+timedelta(minutes=minute)
                bars.append(dict(r,bar_id=r['bar_id']+f'-{minute}',bar_start=stamp,bar_end=stamp+timedelta(minutes=1),available_at=stamp+timedelta(minutes=1)))
    table=pa.Table.from_pylist(bars,schema=BAR_SCHEMA)
    values=pa.Table.from_pylist([feature(s,100,at) for s in ['TEST','NIFTY_50','BANK_NIFTY']],schema=FEATURE_SCHEMA)
    kwargs=dict(as_of=at,sector_map={'TEST':'SECTOR'},index_symbols=('NIFTY_50','BANK_NIFTY'),vix_symbol='VIX',vix_percentile_method='weak',vix_thresholds=(25,75),time_boundaries=BOUNDARIES,value_thresholds=(100,1000),spread_thresholds=(.01,.05),index_policy='unanimous',advancer_basis='prior_close',universe=('TEST',))
    out=context_snapshot(table,values,pa.Table.from_pylist(quote_rows,schema=TICK_SCHEMA),pa.Table.from_pylist(levels,schema=LEVEL_SCHEMA),pa.Table.from_pylist(announcements,schema=EVENT_SCHEMA),**kwargs).to_pylist()[0]
    assert out['index_regime']=='TREND_UP' and out['vix_regime']=='NORMAL'
    assert out['sector_rs_5d']==pytest.approx(.05) and out['liquidity_tier']==1
    assert out['event_flags']==['recent_announcement']
    assert 'LIQUIDITY_VALUE_APPROXIMATE' in out['flags']
    assert {r['record_id'] for r in out['inputs']}&{'1','2','3'}=={'1'}
    assert all(r['available_at']<=at for r in out['inputs'])


def test_incomplete_breadth_is_null_not_a_partial_universe_fraction():
    bars=time_bars(classify_ticks(ticks([(100,0,99,101,[]),(110,10,99,101,[])])),minutes=1,as_of=START+timedelta(minutes=1))
    at=START+timedelta(minutes=1)
    values=pa.Table.from_pylist([feature('TEST',105,at)],schema=FEATURE_SCHEMA)
    out=snapshot(bars,values,at,universe=('TEST','MISSING')).to_pylist()[0]
    assert out['breadth_above_vwap_fraction'] is None
    assert 'BREADTH_PRICE_MISSING' in out['flags']


def test_t11_event_direction_requires_15m_and_confirmed_availability():
    at=START+timedelta(minutes=1)
    prototype=time_bars(classify_ticks(ticks([(100,0,99,101,[]),(110,10,99,101,[])])),minutes=1,as_of=at).to_pylist()[0]
    bars=pa.Table.from_pylist([dict(prototype,symbol=s,instrument_key='KEY|'+s,bar_id=s) for s in ['TEST','NIFTY_50','BANK_NIFTY']],schema=BAR_SCHEMA)
    values=pa.Table.from_pylist([feature(s,100,at) for s in ['TEST','NIFTY_50','BANK_NIFTY']],schema=FEATURE_SCHEMA)
    events=[]
    for s,tf,side,available in [('NIFTY_50',15,'BUY',START),('BANK_NIFTY',15,'BUY',START),('NIFTY_50',1,'SELL',at),('BANK_NIFTY',15,'SELL',at+timedelta(seconds=1))]:
        events.append(dict(symbol=s,instrument_key='KEY|'+s,session_date=START.date(),event_id=f'KEY|{s}:{tf}:BOS:bar:{side}:100',event_type='BOS',occurred_at=START,confirmed_at=START,price=D('100'),side=side,strength=None,zone_id=None,source='SIM',method='BAR_STRUCTURE',confidence='HIGH',flags=[],available_at=available,inputs=[]))
    result=context_snapshot(bars,values,pa.Table.from_pylist([],schema=TICK_SCHEMA),pa.Table.from_pylist([],schema=LEVEL_SCHEMA),pa.Table.from_pylist(events,schema=EVENT_SCHEMA),as_of=at,sector_map={},index_symbols=('NIFTY_50','BANK_NIFTY'),vix_symbol='VIX',vix_percentile_method='weak',vix_thresholds=(25,75),time_boundaries=BOUNDARIES,value_thresholds=(100,1000),spread_thresholds=(.01,.05),index_policy='unanimous',advancer_basis='session_open',universe=('TEST',))
    assert result.to_pylist()[0]['index_regime']=='TREND_UP'
