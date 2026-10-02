"""Canonical T10 event joins preserve availability and causal confirmation."""
from datetime import timedelta
from decimal import Decimal as D
import pyarrow as pa
from test_trades_bars import START
from orderflow.schema import FEATURE_SCHEMA,EVENT_SCHEMA,BAR_SCHEMA
from orderflow.layers.vwap.core import vwap_event_table


def bars(spec):
    rows=[]
    for i,(high,low,delta,cvd,mid) in enumerate(spec):
        start=START+timedelta(minutes=i);end=start+timedelta(minutes=1)
        rows.append(dict(symbol='TEST',instrument_key='NSE_EQ|TEST',session_date=START.date(),bar_id=f'b{i}',bar_kind='TIME',
            bar_start=start,bar_end=end,timeframe_minutes=1,volume_target=None,open=D(str(low)),high=D(str(high)),low=D(str(low)),
            close=D(str(mid)),mid_close=D(str(mid)),volume=abs(delta),buy_volume=max(delta,0),sell_volume=max(-delta,0),unknown_volume=0,
            delta=delta,cvd=cvd,source='SIMULATOR',method='ESTIMATE',confidence='LOW',flags=[],available_at=end,inputs=[]))
    return pa.Table.from_pylist(rows,schema=BAR_SCHEMA)


def features(count=6):
    rows=[]
    for i in range(count):
        end=START+timedelta(minutes=i+1)
        for name,value in [('SESSION_VWAP',100.),('SESSION_SIGMA',1.)]:
            rows.append(dict(symbol='TEST',instrument_key='NSE_EQ|TEST',session_date=START.date(),minute=end,name=name,level=None,value=value,
                r_squared=None,n=i+1,unknown_share=None,window_start=START,window_end=end,source='SIMULATOR',method='ESTIMATE',confidence='LOW',
                flags=[],available_at=end,inputs=[dict(record_id=f'{name}:{i}',available_at=end)]))
    return pa.Table.from_pylist(rows,schema=FEATURE_SCHEMA)


def fixture():
    return bars([(p+1,p-1,10,10*(i+1),p) for i,p in enumerate([98,99,101,103,104,105])])


def test_canonical_reclaim_acceptance_and_confirming_inputs():
    out=vwap_event_table(fixture(),features(),as_of=START+timedelta(minutes=6))
    assert out.schema.equals(EVENT_SCHEMA)
    rows=out.to_pylist();reclaim=next(r for r in rows if r['event_type']=='VWAP_RECLAIM')
    assert reclaim['side']=='BUY' and reclaim['price']==D('101') and reclaim['available_at']==START+timedelta(minutes=3)
    assert {'b0','b1','b2'}<={r['record_id'] for r in reclaim['inputs']}
    accept=next(r for r in rows if r['event_type']=='BAND_ACCEPTANCE')
    assert accept['confirmed_at']==START+timedelta(minutes=6)
    assert {'b3','b4','b5'}<={r['record_id'] for r in accept['inputs']}
    assert all(ref['available_at']<=event['available_at'] for event in rows for ref in event['inputs'])


def test_no_future_feature_backdating_and_first_join_remains_immutable():
    data=bars([(102,99,1,1,101)])
    rows=features(1).to_pylist();rows[1]['available_at']=START+timedelta(minutes=2)
    late=pa.Table.from_pylist(rows,schema=FEATURE_SCHEMA)
    assert vwap_event_table(data,late,as_of=START+timedelta(minutes=1)).num_rows==0
    out=vwap_event_table(data,late,as_of=START+timedelta(minutes=2)).to_pylist()
    assert out and all(r['available_at']==START+timedelta(minutes=2) for r in out)
    assert all('LATE_VWAP' in r['flags'] for r in out)
    # A later revision to the same snapshot must not revise a first eligible join.
    revision=features(1).to_pylist()
    for row in revision:
        row['available_at']=START+timedelta(minutes=3);row['value']=500
    full=pa.concat_tables([features(1),pa.Table.from_pylist(revision,schema=FEATURE_SCHEMA)])
    assert vwap_event_table(data,full,as_of=START+timedelta(minutes=3)).equals(vwap_event_table(data,features(1),as_of=START+timedelta(minutes=3)))


def test_same_instrument_session_and_no_future_minute_join():
    data=bars([(102,99,1,1,101)]);rows=features(1).to_pylist()
    for row in rows:row['minute']=START+timedelta(minutes=2)
    assert vwap_event_table(data,pa.Table.from_pylist(rows,schema=FEATURE_SCHEMA),as_of=START+timedelta(minutes=3)).num_rows==0
    for row in rows:
        row['minute']=START+timedelta(minutes=1);row['instrument_key']='OTHER'
    assert vwap_event_table(data,pa.Table.from_pylist(rows,schema=FEATURE_SCHEMA),as_of=START+timedelta(minutes=3)).num_rows==0
    for row in rows:
        row['instrument_key']='NSE_EQ|TEST';row['session_date']+=timedelta(days=1)
    assert vwap_event_table(data,pa.Table.from_pylist(rows,schema=FEATURE_SCHEMA),as_of=START+timedelta(minutes=3)).num_rows==0


def test_late_prior_bar_cannot_backdate_or_false_confirm_reclaim():
    data=fixture().to_pylist();data[0]['available_at']=START+timedelta(minutes=4)
    out=vwap_event_table(pa.Table.from_pylist(data,schema=BAR_SCHEMA),features(),as_of=START+timedelta(minutes=6)).to_pylist()
    assert not [r for r in out if r['event_type']=='VWAP_RECLAIM']
    assert any('OUT_OF_ORDER' in r['flags'] for r in out)


def test_event_history_approximate_method_and_quality_propagate():
    data=bars([(102,99,1,1,101)]);rows=features(1).to_pylist()
    for row in rows:
        row['method']='APPROXIMATE';row['flags']=['GAP']
    out=vwap_event_table(data,pa.Table.from_pylist(rows,schema=FEATURE_SCHEMA),as_of=START+timedelta(minutes=1)).to_pylist()
    assert out and all(r['method']=='APPROXIMATE' and 'GAP' in r['flags'] for r in out)


def test_closed_bars_and_all_inputs_truncation():
    data=fixture();fs=features();end=START+timedelta(minutes=6)
    for i in range(1,7):
        cutoff=START+timedelta(minutes=i)
        assert vwap_event_table(data,fs,as_of=cutoff).equals(vwap_event_table(data.slice(0,i),fs.slice(0,i*2),as_of=cutoff))
    cutoff=end-timedelta(microseconds=1)
    assert not [e for e in vwap_event_table(data,fs,as_of=cutoff).to_pylist() if e['event_type']=='BAND_ACCEPTANCE']


def test_dependency_later_than_feature_record_delays_event_and_flags():
    data=bars([(102,99,1,1,101)]);rows=features(1).to_pylist()
    rows[0]['inputs'].append(dict(record_id='late-dependency',available_at=START+timedelta(minutes=2)))
    fs=pa.Table.from_pylist(rows,schema=FEATURE_SCHEMA)
    assert vwap_event_table(data,fs,as_of=START+timedelta(minutes=1)).num_rows==0
    out=vwap_event_table(data,fs,as_of=START+timedelta(minutes=2)).to_pylist()
    assert out and all(r['available_at']==START+timedelta(minutes=2) and 'SOURCE_AVAILABLE_AFTER_RECORD' in r['flags'] for r in out)
    assert all(any(ref['record_id']=='late-dependency' for ref in row['inputs']) for row in out)


def test_gap_and_flagged_duplicate_cannot_confirm_acceptance():
    data=fixture().to_pylist();data[4]['flags']=['DUPLICATE']
    out=vwap_event_table(pa.Table.from_pylist(data,schema=BAR_SCHEMA),features(),as_of=START+timedelta(minutes=6)).to_pylist()
    assert not [e for e in out if e['event_type']=='BAND_ACCEPTANCE']
    assert any('DUPLICATE' in e['flags'] for e in out)


def test_feature_gap_breaks_three_consecutive_close_confirmation():
    fs=features().to_pylist()
    for feature in fs:
        if feature['minute']==START+timedelta(minutes=5):feature['flags']=['GAP']
    out=vwap_event_table(fixture(),pa.Table.from_pylist(fs,schema=FEATURE_SCHEMA),as_of=START+timedelta(minutes=6)).to_pylist()
    assert not [e for e in out if e['event_type']=='BAND_ACCEPTANCE']
