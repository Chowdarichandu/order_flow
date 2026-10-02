"""T11 exact SMC structures and point-in-time confirmation tests."""
from datetime import timedelta
from decimal import Decimal as D
import pyarrow as pa
import pytest
from orderflow.schema import BAR_SCHEMA, LEVEL_SCHEMA, EVENT_SCHEMA
from orderflow.layers.smc.core import atr_values, fractals, displacement, dealing_range, timeframe_bias, smc
from test_trades_bars import START


def bars(points):
    rows=[]
    for i,(o,h,l,c) in enumerate(points):
        t=START+timedelta(minutes=i)
        rows.append(dict(symbol='TEST',instrument_key='NSE_EQ|TEST',session_date=START.date(),bar_id=f'b{i}',bar_kind='TIME',bar_start=t,bar_end=t+timedelta(minutes=1),timeframe_minutes=1,volume_target=None,open=D(str(o)),high=D(str(h)),low=D(str(l)),close=D(str(c)),mid_close=None,volume=10,buy_volume=5,sell_volume=5,unknown_volume=0,delta=0,cvd=0,source='TEST',method='ESTIMATE',confidence='LOW',flags=[],available_at=t+timedelta(minutes=1),inputs=[]))
    return pa.Table.from_pylist(rows,schema=BAR_SCHEMA)


def run(data,**kw):
    return smc(data,as_of=kw.pop('as_of',START+timedelta(days=1)),tick_size=D('1'),atr_smoothing='sma',swing_tie_policy='strict',fvg_comparator='ge',atr_period=2,**kw)


def test_atr_requires_policy_and_uses_previous_close():
    data=bars([(10,11,9,10),(15,16,14,15),(15,18,14,17)]).to_pylist()
    assert atr_values(data,period=2,smoothing='sma')==[None,D('4'),D('5')]
    assert atr_values(data,period=2,smoothing='wilder')==[None,D('4'),D('4')]
    with pytest.raises(ValueError): atr_values(data,period=2,smoothing=None)


def test_fractal_confirmed_only_after_right_bars_and_tie_explicit():
    data=bars([(10,11,9,10),(11,12,10,11),(12,15,11,12),(11,13,10,11),(10,12,9,10),(30,35,29,31)])
    cutoff=START+timedelta(minutes=5)
    found=fractals(data,as_of=cutoff,bars_each_side=2,tie_policy='strict')
    assert found==fractals(data.slice(0,5),as_of=cutoff,bars_each_side=2,tie_policy='strict')
    assert len(found)==1 and found[0]['side']=='HIGH' and found[0]['price']==D('15')
    assert found[0]['available_at']==cutoff
    assert not fractals(data,as_of=cutoff-timedelta(seconds=1),bars_each_side=2,tie_policy='strict')


def test_displacement_and_dealing_range_and_mtf():
    assert displacement(dict(open=D('10'),close=D('14'),high=D('15'),low=D('10')),D('3'))
    assert not displacement(dict(open=D('12'),close=D('13'),high=D('15'),low=D('10')),D('3'))
    values=dealing_range(D('100'),D('120'),D('109'),side='BUY')
    assert values['position']=='DISCOUNT' and values['ote_low']==D('104.20') and values['ote_high']==D('107.60')
    assert timeframe_bias('BUY','BUY',side='BUY')=='ALIGNED'
    assert timeframe_bias('SELL','SELL',side='BUY')=='OPPOSED'
    assert timeframe_bias('BUY','SELL',side='BUY')=='MIXED'


def test_fvg_confirmation_partial_fill_full_fill_and_truncation():
    data=bars([(100,101,99,100),(102,104,101,103),(105,107,104,106),(105,106,103,104),(103,104,99,100)])
    cutoff=START+timedelta(minutes=3)
    levels,events=run(data,as_of=cutoff)
    assert levels.schema.equals(LEVEL_SCHEMA) and events.schema.equals(EVENT_SCHEMA)
    fvg=[r for r in levels.to_pylist() if r['type']=='FVG']
    assert len(fvg)==1 and (fvg[0]['low'],fvg[0]['high'])==(D('101'),D('104')) and fvg[0]['state']=='ACTIVE'
    assert levels.equals(run(data.slice(0,3),as_of=cutoff)[0])
    partial=[r for r in run(data,as_of=START+timedelta(minutes=4))[0].to_pylist() if r['record_id']==fvg[0]['record_id']][0]
    assert partial['state']=='PARTIAL_FILL' and partial['mitigated_at']==START+timedelta(minutes=4)
    final=[r for r in run(data)[0].to_pylist() if r['record_id']==fvg[0]['record_id']][0]
    assert final['state']=='FILLED' and final['invalidated_at']==START+timedelta(minutes=5)


def test_fvg_comparator_cannot_be_guessed():
    with pytest.raises(ValueError,match='comparator'):
        smc(bars([]),as_of=START,tick_size=D('1'),atr_smoothing='sma',swing_tie_policy='strict',fvg_comparator=None)


def test_bull_structure_bos_choch_ob_and_lifecycle():
    # N=1: confirmed highs 12,14; lows 8,9 establish an uptrend before close 17.
    data=bars([(10,11,9,10),(11,12,10,11),(10,11,8,10),(12,14,11,12),(11,12,9,10),(11,12,10,11),(11,18,10,17),(17,18,9,11),(10,11,7,8)])
    levels,events=run(data,bars_each_side=1)
    es=events.to_pylist()
    assert any(e['event_type']=='BOS' and e['side']=='BUY' for e in es)
    assert any(e['event_type']=='CHOCH' and e['side']=='SELL' for e in es)
    obs=[r for r in levels.to_pylist() if r['type']=='ORDER_BLOCK' and r['side']=='BUY']
    assert obs and obs[0]['low']==D('9') and obs[0]['high']==D('12')
    assert obs[0]['mitigated_at']==START+timedelta(minutes=8) and obs[0]['invalidated_at']==START+timedelta(minutes=9)


def test_external_pool_sweep_reversal_and_three_close_acceptance():
    proto=bars([(100,101,99,100)]).to_pylist()[0]
    pool={k:proto[k] for k in ('symbol','instrument_key','session_date','source','method','confidence','flags','available_at','inputs')}
    pool.update(record_id='pool',type='PRIOR_DAY_HIGH',timeframe_minutes=None,low=D('105'),high=D('105'),side='SELL',origin_at=START,created_at=START,available_at=START,state='ACTIVE',invalidated_at=None,mitigated_at=None)
    pools=pa.Table.from_pylist([pool],schema=LEVEL_SCHEMA)
    reverse=bars([(104,106,103,104)])
    es=run(reverse,external_pools=pools)[1].to_pylist()
    assert any(e['event_type']=='SWEEP_REVERSAL' and e['side']=='SELL' for e in es)
    continuation=bars([(105,107,104,106),(106,108,105,107),(107,109,106,108)])
    es=run(continuation,external_pools=pools)[1].to_pylist()
    assert any(e['event_type']=='SWEEP_CONTINUATION' and e['confirmed_at']==START+timedelta(minutes=3) for e in es)
    assert not any(e['event_type']=='SWEEP_CONTINUATION' for e in run(continuation,external_pools=pools,as_of=START+timedelta(minutes=2))[1].to_pylist())


def test_equal_swing_pool_and_input_availability():
    data=bars([(10,11,9,10),(11,14,10,11),(10,11,8,10),(11,14,10,11),(10,11,9,10)])
    levels,_=run(data,bars_each_side=1)
    pools=[r for r in levels.to_pylist() if r['type']=='EQUAL_HIGH']
    assert pools and pools[0]['available_at']==START+timedelta(minutes=5)
    for row in levels.to_pylist(): assert all(ref['available_at']<=row['available_at'] for ref in row['inputs'])


def test_bear_fvg_mirror_and_comparator_policies():
    data=bars([(106,107,105,106),(103,105,101,102),(100,102,99,100),(103,106,100,105),(105,108,104,107)])
    first=run(data,as_of=START+timedelta(minutes=3))[0].to_pylist()
    gap=next(r for r in first if r['type']=='FVG' and r['side']=='SELL')
    assert (gap['low'],gap['high'])==(D('102'),D('105'))
    final=next(r for r in run(data)[0].to_pylist() if r['record_id']==gap['record_id'])
    assert final['state']=='FILLED' and final['invalidated_at']==START+timedelta(minutes=5)
    eq=smc(data,as_of=START+timedelta(minutes=3),tick_size=D('1'),atr_smoothing='sma',swing_tie_policy='strict',fvg_comparator='eq',atr_period=2)[0]
    assert not any(r['type']=='FVG' for r in eq.to_pylist())


def test_late_atr_input_delays_displacement_availability():
    data=bars([(100,101,99,100),(100,102,99,101),(100,110,99,109)])
    rows=data.to_pylist(); rows[1]['available_at']=START+timedelta(minutes=10)
    data=pa.Table.from_pylist(rows,schema=BAR_SCHEMA)
    events=run(data)[1].to_pylist()
    event=next(e for e in events if e['event_type']=='DISPLACEMENT')
    assert event['available_at']==START+timedelta(minutes=10)
    assert any(ref['record_id']=='b1' for ref in event['inputs'])


def test_developing_session_pools_available_before_sweep_bar():
    data=bars([(100,105,99,104),(104,106,103,104)])
    levels,events=run(data)
    assert any(r['type']=='SESSION_HIGH' for r in levels.to_pylist())
    assert any(e['event_type']=='SWEEP_REVERSAL' and e['price']==D('105') for e in events.to_pylist())


def test_structure_provenance_preserves_estimate_and_approximate_labels():
    data=bars([(100,101,99,100),(102,104,101,103),(105,120,104,119)])
    levels,events=run(data)
    assert levels.num_rows and events.num_rows
    assert all(r['method']=='ESTIMATE' and r['confidence']=='LOW' for table in (levels,events) for r in table.to_pylist())
    rows=data.to_pylist(); rows[1]['method']='APPROXIMATE'
    levels,_=run(pa.Table.from_pylist(rows,schema=BAR_SCHEMA))
    assert next(r for r in levels.to_pylist() if r['type']=='FVG')['method']=='APPROXIMATE'


def test_approximate_external_pool_label_propagates_to_sweep():
    proto=bars([(100,101,99,100)]).to_pylist()[0]
    pool={k:proto[k] for k in ('symbol','instrument_key','session_date','source','method','confidence','flags','available_at','inputs')}
    pool.update(record_id='approx-pool',type='PRIOR_DAY_HIGH',timeframe_minutes=None,low=D('105'),high=D('105'),side='SELL',origin_at=START,created_at=START,available_at=START,state='ACTIVE',invalidated_at=None,mitigated_at=None,method='APPROXIMATE')
    pools=pa.Table.from_pylist([pool],schema=LEVEL_SCHEMA)
    es=run(bars([(104,106,103,104)]),external_pools=pools)[1].to_pylist()
    assert next(e for e in es if e['event_type']=='SWEEP_REVERSAL')['method']=='APPROXIMATE'
