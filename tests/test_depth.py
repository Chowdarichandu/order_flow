"""T07 crafted-book known answers and causal depth events."""
from decimal import Decimal as D
from orderflow.layers.orderflow.depth import depth_imbalance,ofi,multi_ofi,sweep,iceberg


def level(price,qty):return {'price':D(str(price)),'quantity':qty,'orders':None}


def test_depth_imbalance_known_and_zero_depth():
    assert depth_imbalance([level(100,30)],[level(101,10)],levels=1)==.5
    assert depth_imbalance([],[],levels=5) is None
    assert depth_imbalance([level(100,10),level(99,10)],[level(101,30)],levels=2)==-.2


def test_cont_ofi_same_improved_and_worsened_quotes():
    old={'bid':level(100,10),'ask':level(101,20)}
    assert ofi(old,{'bid':level(100,15),'ask':level(101,18)})==7
    assert ofi(old,{'bid':level(100.1,12),'ask':level(101.1,19)})==32
    assert ofi(old,{'bid':level(99.9,12),'ask':level(100.9,19)})==-29


def test_multi_level_normalization_uses_trailing_depth_only():
    previous={'bids':[level(100,10),level(99,20)],'asks':[level(101,20),level(102,20)]}
    current={'bids':[level(100,15),level(99,25)],'asks':[level(101,18),level(102,18)]}
    result=multi_ofi(previous,current,average_depth=[15,20])
    assert result['per_level']==[7,7]
    assert abs(result['normalized_sum']-(7/15+7/20))<1e-12


def test_book_sweep_requires_volume_and_three_displayed_levels():
    old={'asks':[level(101+i*.05,10) for i in range(5)],'bids':[level(100-i*.05,10) for i in range(5)]}
    new={'asks':[level(101.15,10)],'bids':[level(100,10)]}
    assert sweep(old,new,traded_volume=30,k=3)=='BUY'
    assert sweep(old,new,traded_volume=0,k=3) is None
    assert sweep(old,{'asks':[level(101.1,10)],'bids':[level(100,10)]},traded_volume=20,k=3) is None


def test_iceberg_strict_factor_stationary_level_and_two_refills():
    snapshots=[{'price':D('100'),'quantity':10,'traded_volume':10},
               {'price':D('100'),'quantity':5,'traded_volume':10},
               {'price':D('100'),'quantity':10,'traded_volume':10},
               {'price':D('100'),'quantity':5,'traded_volume':10},
               {'price':D('100'),'quantity':10,'traded_volume':1}]
    assert iceberg(snapshots,factor=3,min_refills=2)=={'detected':True,'refills':2,'method':'HEURISTIC'}
    assert not iceberg(snapshots[:3],factor=3,min_refills=2)['detected']
    snapshots[-1]['price']=D('100.05')
    assert not iceberg(snapshots,factor=3,min_refills=2)['detected']


def test_depth_feature_availability_and_truncation():
    from test_trades_bars import ticks
    from orderflow.layers.orderflow.depth import depth_features
    data=ticks([(100,0,99,101,[]),(101,10,99,101,[]),(100,30,99,101,[])])
    full=depth_features(data,levels=1,trailing_window=2,iceberg_window=3)
    short=depth_features(data.slice(0,2),levels=1,trailing_window=2,iceberg_window=3)
    assert full.slice(0,short.num_rows).equals(short)
    assert all(r['available_at']==r['minute'] for r in full.to_pylist())
    assert [r['value'] for r in full.to_pylist() if r['name']=='DI_1']==[0,0,0]


def feature_table(rows):
    import pyarrow as pa
    from orderflow.schema import TICK_SCHEMA
    return pa.Table.from_pylist(rows,schema=TICK_SCHEMA)


def feature_rows(rows,**kwargs):
    from orderflow.layers.orderflow.depth import depth_features
    return depth_features(feature_table(rows),levels=kwargs.pop('levels',1),
                          trailing_window=2,iceberg_window=5,**kwargs).to_pylist()


def changing_book_rows():
    from test_trades_bars import ticks
    rows=ticks([(101,0,100,101,[]),(101,10,100,101,[]),(101,20,100,101,[]) ]).to_pylist()
    for row,bid,ask in zip(rows,[10,15,20],[20,18,16]):
        row['bids'][0]['quantity']=bid;row['asks'][0]['quantity']=ask
    return rows


def test_interval_ofi_sums_snapshot_contributions_and_resets_each_minute():
    from datetime import timedelta
    rows=changing_book_rows()
    extra=dict(rows[-1],sequence=3,vtt=30,
               receipt_ts=rows[0]['receipt_ts']+timedelta(minutes=1),
               exchange_ts=rows[0]['exchange_ts']+timedelta(minutes=1))
    extra['bids']=[level(100,25)];extra['asks']=[level(101,14)]
    out=feature_rows(rows+[extra])
    values=[r for r in out if r['name']=='OFI_INTERVAL' and r['level']==1]
    assert [r['value'] for r in values]==[None,7,14,7]
    assert all(r['window_start'].second==0 and r['window_start'].microsecond==0 for r in values)
    assert all(r['window_end']==r['available_at'] for r in values)


def test_feature_normalization_trailing_average_and_input_availability():
    rows=changing_book_rows()
    out=feature_rows(rows)
    normalized=[r for r in out if r['name']=='OFI_NORMALIZED' and r['level']==1]
    assert len(normalized)==3 and normalized[0]['value'] is None
    assert abs(normalized[1]['value']-7/15.75)<1e-12
    assert abs(normalized[2]['value']-7/17.25)<1e-12
    assert all(ref['available_at']<=r['available_at'] for r in out for ref in r['inputs'])


def test_missing_depth_nulls_ofi_and_partial_depth_is_flagged():
    rows=changing_book_rows()
    rows[1]['bids']=[]
    out=feature_rows(rows,levels=2)
    for row in out:
        assert 'PARTIAL_DEPTH' in row['flags']
    missing=[r for r in out if r['available_at']==rows[1]['receipt_ts']]
    assert next(r for r in missing if r['name']=='DI_2')['value'] is None
    assert [r['value'] for r in missing if r['name']=='OFI']==[None,None]
    final=[r for r in out if r['available_at']==rows[2]['receipt_ts']]
    assert [r['value'] for r in final if r['name']=='OFI']==[None,None]


def test_unflagged_receipt_regression_has_no_future_inputs_or_state_update():
    from datetime import timedelta
    rows=changing_book_rows()
    stale=dict(rows[1],sequence=99,receipt_ts=rows[0]['receipt_ts']-timedelta(seconds=1))
    out=feature_rows(rows[:1]+[stale]+rows[1:])
    bad=[r for r in out if r['available_at']==stale['receipt_ts']]
    assert bad and all('OUT_OF_ORDER' in r['flags'] and r['value'] is None for r in bad)
    assert all(ref['available_at']<=r['available_at'] for r in out for ref in r['inputs'])
    assert [r['value'] for r in out if r['name']=='OFI' and r['level']==1]==[None,None,7,7]


def test_duplicate_and_exchange_regression_do_not_change_ofi_state():
    from datetime import timedelta
    rows=changing_book_rows()
    duplicate=dict(rows[0],sequence=1,receipt_ts=rows[1]['receipt_ts'],flags=['DUPLICATE'])
    regressed=dict(rows[1],sequence=2,receipt_ts=rows[1]['receipt_ts']+timedelta(seconds=1),
                   exchange_ts=rows[0]['exchange_ts']-timedelta(seconds=1))
    valid=dict(rows[1],sequence=3,receipt_ts=rows[2]['receipt_ts'])
    out=feature_rows(rows[:1]+[duplicate,regressed,valid])
    assert [r['value'] for r in out if r['name']=='OFI' and r['level']==1]==[None,None,None,7]
    assert all('OUT_OF_ORDER' in r['flags'] for r in out if r['available_at']==regressed['receipt_ts'])


def test_iceberg_feature_uses_level_trade_volume_and_detects_after_second_refill():
    from test_trades_bars import ticks
    rows=ticks([(101,0,100,101,[]),(101,11,100,101,[]),(101,22,100,101,[]),
                (101,33,100,101,[]),(101,44,100,101,[])]).to_pylist()
    for row,qty in zip(rows,[10,5,10,5,10]):row['asks'][0]['quantity']=qty
    out=feature_rows(rows)
    events=[r for r in out if r['name']=='ICEBERG_BUY']
    assert len(events)==1 and events[0]['available_at']==rows[-1]['receipt_ts']
    assert events[0]['method']=='HEURISTIC'
    assert len(events[0]['inputs'])==5
    rows[-1]['flags']=['VOLUME_RESET']
    rows[-1]['vtt']=1000
    out=feature_rows(rows)
    assert not any(r['name']=='ICEBERG_BUY' for r in out)


def test_depth_handles_missing_exchange_timestamp_and_inferred_reset_flags():
    rows=changing_book_rows()
    rows[0]['exchange_ts']=None
    rows[1]['exchange_ts']=None
    rows[2]['vtt']=1
    out=feature_rows(rows)
    assert all('VOLUME_RESET' in r['flags'] for r in out if r['available_at']==rows[2]['receipt_ts'])
    assert [r['value'] for r in out if r['name']=='OFI' and r['level']==1]==[None,7,7]


def test_depth_streaming_batches_equal_single_table_and_preserve_truncation():
    import pyarrow as pa
    from orderflow.layers.orderflow.depth import depth_features,depth_feature_batches
    rows=changing_book_rows()
    table=feature_table(rows)
    options=dict(levels=1,trailing_window=2,iceberg_window=5)
    full=depth_features(table,**options)
    streaming=pa.concat_tables(list(depth_feature_batches(
        [table.slice(0,1),table.slice(1,1),table.slice(2,1)],output_batch_size=4,**options)))
    assert streaming.equals(full)
    short=depth_features(table.slice(0,2),**options)
    assert full.slice(0,short.num_rows).equals(short)


def test_sell_sweep_mirror_and_zero_depth_normalization():
    old={'asks':[level(101+i*.05,10) for i in range(5)],
         'bids':[level(100-i*.05,10) for i in range(5)]}
    current={'asks':[level(101,10)],'bids':[level(99.85,10)]}
    assert sweep(old,current,traded_volume=20,k=3)=='SELL'
    result=multi_ofi(old,old,average_depth=[0,1,1,1,1])
    assert result['normalized_per_level'][0] is None
    assert result['normalized_sum'] is None
