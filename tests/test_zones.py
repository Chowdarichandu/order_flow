"""T14 causal interval clustering, source identity, touches and invalidation."""
from datetime import timedelta
from decimal import Decimal as D
import pyarrow as pa
import pytest
from orderflow.schema import LEVEL_SCHEMA,FEATURE_SCHEMA,BAR_SCHEMA,ZONE_SCHEMA
from test_trades_bars import START,ticks
from orderflow.bars.core import time_bars
from orderflow.trades.core import classify_ticks
from orderflow.zones.core import ZonePolicy,cluster_intervals,zone_snapshot


def component(name,low,high=None,kind='POC',side='SUPPORT',created=START,**changes):
    row=dict(symbol='TEST',instrument_key='NSE_EQ|TEST',session_date=START.date(),
             record_id=name,type=kind,timeframe_minutes=None,low=D(str(low)),
             high=D(str(high if high is not None else low)),side=side,origin_at=created,
             created_at=created,invalidated_at=None,mitigated_at=None,state='ACTIVE',
             source='SIMULATOR',method='ESTIMATE',confidence='LOW',flags=[],
             available_at=created,inputs=[])
    row.update(changes);return row


def levels(rows):return pa.Table.from_pylist(rows,schema=LEVEL_SCHEMA)


def atr(value=4,available=START):
    return pa.Table.from_pylist([dict(symbol='TEST',instrument_key='NSE_EQ|TEST',
        session_date=START.date(),minute=available,name='ATR_14_5M',level=5,value=value,
        r_squared=None,n=14,unknown_share=None,window_start=None,window_end=available,
        source='SIMULATOR',method='ESTIMATE',confidence='LOW',flags=[],available_at=available,
        inputs=[])],schema=FEATURE_SCHEMA)


def bars(spec):
    table=classify_ticks(ticks([(price,10*i,99,101,[]) for i,price in enumerate(spec)]))
    return time_bars(table,minutes=1,as_of=START+timedelta(minutes=5))


def policy(**changes):
    values=dict(linkage='single_linkage',touch_policy='entry_episode',
                invalidation_policy='close_beyond_edge',
                side_policy='source_side_else_creation_close',freshness_policy='cluster_formation',
                max_age_minutes=None)
    values.update(changes);return ZonePolicy(**values)


def test_single_linkage_transitive_interval_distance_and_inclusive_threshold():
    rows=[component('a',100,101),component('b',102),component('c',103),component('d',105)]
    groups=cluster_intervals(rows,tolerance=D('1'),linkage='single_linkage')
    assert [[r['record_id'] for r in group] for group in groups]==[['a','b','c'],['d']]
    complete=cluster_intervals(rows,tolerance=D('1'),linkage='complete_linkage')
    assert [[r['record_id'] for r in group] for group in complete]==[['a','b'],['c'],['d']]


def test_zone_components_are_location_metadata_not_votes_and_dedup_source():
    source=[component('a',100,kind='POC'),component('b',101,kind='VWAP'),
            component('b',101,kind='VWAP')]
    out=zone_snapshot(levels(source),bars([100]*6),atr(),
                      as_of=START+timedelta(minutes=1),policy=policy())
    assert out.schema.equals(ZONE_SCHEMA) and out.num_rows==1
    row=out.to_pylist()[0]
    assert (row['low'],row['high'],row['distinct_types'])==(D('100'),D('101'),2)
    assert [c['record_id'] for c in row['components']]==['a','b']
    assert row['side']=='SUPPORT' and row['invalidation_price']==D('100')
    assert row['freshness_minutes']==1


def test_zone_snapshot_uses_latest_available_revision_not_future_invalidation():
    first=component('a',100)
    future=component('a',110,available_at=START+timedelta(minutes=2),
                     invalidated_at=START+timedelta(minutes=2),state='INVALIDATED')
    cutoff=START+timedelta(minutes=1)
    full=zone_snapshot(levels([first,future]),bars([100]*6),atr(),as_of=cutoff,policy=policy())
    prefix=zone_snapshot(levels([first]),bars([100]*6),atr(),as_of=cutoff,policy=policy())
    assert full.equals(prefix) and full.num_rows==1
    assert zone_snapshot(levels([first,future]),bars([100]*6),atr(),
                         as_of=START+timedelta(minutes=2),policy=policy()).num_rows==0


def test_future_component_and_future_atr_are_excluded_and_input_timestamps_causal():
    cutoff=START+timedelta(minutes=1)
    source=levels([component('a',100),component('b',100,kind='FVG',created=cutoff+timedelta(minutes=1))])
    out=zone_snapshot(source,bars([100]*6),atr(),as_of=cutoff,policy=policy()).to_pylist()
    assert out[0]['distinct_types']==1
    assert all(ref['available_at']<=r['available_at'] for r in out for ref in r['inputs'])
    with pytest.raises(ValueError,match='available ATR'):
        zone_snapshot(source,bars([100]*6),atr(available=cutoff+timedelta(minutes=1)),
                      as_of=cutoff,policy=policy())


def manual_bars(spec):
    base=bars([100]*6).to_pylist()[0]
    rows=[]
    for i,(low,high,close) in enumerate(spec):
        end=START+timedelta(minutes=i+1)
        row=dict(base,bar_start=end-timedelta(minutes=1),bar_end=end,
                 open=D(str(close)),low=D(str(low)),high=D(str(high)),close=D(str(close)),
                 available_at=end)
        rows.append(row)
    return pa.Table.from_pylist(rows,schema=BAR_SCHEMA)


def test_zone_entry_episodes_count_one_touch_until_exit_and_return():
    table=manual_bars([(99,101,101),(99,101,101),(102,103,103),(99,101,101)])
    out=zone_snapshot(levels([component('a',100)]),table,atr(),
                      as_of=START+timedelta(minutes=4),policy=policy()).to_pylist()[0]
    assert out['touches']==2 and out['invalidated_at'] is None
    each=zone_snapshot(levels([component('a',100)]),table,atr(),
                       as_of=START+timedelta(minutes=4),
                       policy=policy(touch_policy='every_intersecting_bar')).to_pylist()[0]
    assert each['touches']==3


def test_invalidation_close_strict_beyond_edge_only_after_close_and_side_mirror():
    source=levels([component('a',100)])
    table=manual_bars([(99,101,100),(99,100,99)])
    before=zone_snapshot(source,table,atr(),as_of=START+timedelta(minutes=1),policy=policy())
    assert before.to_pylist()[0]['invalidated_at'] is None
    after=zone_snapshot(source,table,atr(),as_of=START+timedelta(minutes=2),policy=policy())
    assert after.to_pylist()[0]['invalidated_at']==START+timedelta(minutes=2)
    resistance=zone_snapshot(levels([component('a',100,side='RESISTANCE')]),
        manual_bars([(99,101,100),(100,101,101)]),atr(),
        as_of=START+timedelta(minutes=2),policy=policy()).to_pylist()[0]
    assert resistance['invalidation_price']==D('100')
    assert resistance['invalidated_at']==START+timedelta(minutes=2)


def test_freshness_explicit_policy_expiry_and_new_component_identity():
    source=levels([component('a',100),component('b',101,created=START+timedelta(minutes=1))])
    cutoff=START+timedelta(minutes=3)
    cluster=zone_snapshot(source,bars([101]*6),atr(),as_of=cutoff,policy=policy()).to_pylist()[0]
    assert cluster['created_at']==START+timedelta(minutes=1) and cluster['freshness_minutes']==2
    oldest=zone_snapshot(source,bars([101]*6),atr(),as_of=cutoff,
                         policy=policy(freshness_policy='oldest_component')).to_pylist()[0]
    assert oldest['freshness_minutes']==3
    expired=zone_snapshot(source,bars([101]*6),atr(),as_of=cutoff,
                          policy=policy(max_age_minutes=1))
    assert expired.num_rows==0


def test_explicit_policies_invalid_arguments_and_conflicting_source_identity():
    with pytest.raises(ValueError,match='linkage'):
        cluster_intervals([],tolerance=D('1'),linkage='made_up')
    with pytest.raises(ValueError,match='contradictory'):
        zone_snapshot(levels([component('a',100),component('a',101)]),bars([100]*6),
                      atr(),as_of=START+timedelta(minutes=1),policy=policy())


def test_layer_adapter_collects_active_profile_vwap_and_source_levels_causally():
    from orderflow.schema import PROFILE_SCHEMA
    from orderflow.zones.core import collect_zone_levels
    cutoff=START+timedelta(minutes=1)
    profile=dict(symbol='TEST',instrument_key='NSE_EQ|TEST',session_date=START.date(),
        minute=cutoff,profile_kind='SESSION',sessions=1,levels=[],poc=D('100'),vah=D('101'),
        val=D('99'),vwap=D('100'),ib_high=None,ib_low=None,hvn=[D('100.5')],lvn=[],
        source='SIMULATOR',method='ESTIMATE',confidence='LOW',flags=[],available_at=cutoff,inputs=[])
    profiles=pa.Table.from_pylist([profile,dict(profile,minute=cutoff+timedelta(minutes=1),
        available_at=cutoff+timedelta(minutes=1),poc=D('110'))],schema=PROFILE_SCHEMA)
    feature=atr().to_pylist()[0]
    feature.update(name='SESSION_VWAP',value=100,minute=cutoff,available_at=cutoff)
    features=pa.Table.from_pylist([feature],schema=FEATURE_SCHEMA)
    source=levels([component('ob',99,100,kind='OB')])
    collected=collect_zone_levels(source,profiles,features,as_of=cutoff,
                                 feature_types={'SESSION_VWAP':'VWAP'})
    assert collected.schema.equals(LEVEL_SCHEMA)
    assert sorted(r['type'] for r in collected.to_pylist())==['HVN','OB','POC','VAH','VAL','VWAP']
    assert all(r['low']<D('110') for r in collected.to_pylist())
    out=zone_snapshot(collected,manual_bars([(99,101,101)]),atr(),
                      as_of=cutoff,policy=policy()).to_pylist()
    assert out and out[0]['distinct_types']==6


def test_zone_ids_are_permutation_invariant_and_instruments_never_cluster_together():
    source=[component('a',100),component('b',101,kind='VWAP')]
    options=dict(as_of=START+timedelta(minutes=1),policy=policy())
    one=zone_snapshot(levels(source),bars([101]*6),atr(),**options)
    two=zone_snapshot(levels(list(reversed(source))),bars([101]*6),atr(),**options)
    assert one.equals(two)
    other=component('a',100,symbol='OTHER',instrument_key='NSE_EQ|OTHER')
    other_atr=dict(atr().to_pylist()[0],symbol='OTHER',instrument_key='NSE_EQ|OTHER')
    atrs=pa.concat_tables([atr(),pa.Table.from_pylist([other_atr],schema=FEATURE_SCHEMA)])
    result=zone_snapshot(levels(source+[other]),bars([101]*6),atrs,**options)
    assert result.num_rows==2


def test_source_future_inputs_are_rejected_and_duplicate_bars_cannot_add_touches():
    bad=component('bad',100,inputs=[dict(record_id='future',available_at=START+timedelta(minutes=1))])
    with pytest.raises(ValueError,match='future input'):
        zone_snapshot(levels([bad]),bars([100]*6),atr(),
                      as_of=START+timedelta(minutes=1),policy=policy())
    table=manual_bars([(99,101,101)])
    out=zone_snapshot(levels([component('a',100)]),pa.concat_tables([table,table]),atr(),
                      as_of=START+timedelta(minutes=1),
                      policy=policy(touch_policy='every_intersecting_bar')).to_pylist()[0]
    assert out['touches']==1


def test_delayed_component_forms_zone_only_after_receipt_without_prior_touches():
    delayed=component('a',100,available_at=START+timedelta(minutes=2))
    history=manual_bars([(99,101,101),(99,101,101),(102,103,103)])
    out=zone_snapshot(levels([delayed]),history,atr(),as_of=START+timedelta(minutes=3),
                      policy=policy()).to_pylist()[0]
    assert out['created_at']==START+timedelta(minutes=2)
    assert out['freshness_minutes']==1 and out['touches']==0


def test_adapter_latest_null_removes_prior_price_sigma_and_or_diagnostics():
    from orderflow.schema import PROFILE_SCHEMA
    from orderflow.zones.core import collect_zone_levels
    empty=pa.Table.from_pylist([],schema=PROFILE_SCHEMA)
    cutoff=START+timedelta(minutes=1)
    first=atr().to_pylist()[0]
    first.update(name='SESSION_VWAP',value=100)
    latest=dict(first,minute=cutoff,available_at=cutoff,value=None)
    sigma=dict(first,name='SESSION_SIGMA',value=2)
    band=dict(first,name='SESSION_BAND_UP_2',value=104)
    anchor=dict(first,name='ANCHOR_SWING1_VWAP',value=102)
    features=pa.Table.from_pylist([first,latest,sigma,band,anchor],schema=FEATURE_SCHEMA)
    incomplete=component('or','99',101,kind='OR5_INCOMPLETE',state='INCOMPLETE')
    out=collect_zone_levels(levels([incomplete]),empty,features,as_of=cutoff).to_pylist()
    assert sorted(r['type'] for r in out)==['ANCHORED_VWAP','VWAP_BAND']
