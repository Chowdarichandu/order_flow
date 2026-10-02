"""Known-answer and causal-prefix tests for the frozen EXPLORATORY registry."""
from datetime import datetime, timedelta, timezone, date
from types import SimpleNamespace

import numpy as np
import pytest

from orderflow.research.edge_strategies import load_variants, generate_targets


def panel(n=400, hourly=False):
    start=datetime(2022,1,3,3,45,tzinfo=timezone.utc)
    times=[]
    d=start
    while len(times)<n:
        if d.weekday()<5 and (not hourly or 3<=d.hour<=9):
            times.append(d)
        d+=timedelta(hours=1) if hourly else timedelta(days=1)
    base=np.arange(n,dtype=float)
    close=np.column_stack((100+base,100+base*.3,100+base*.1))
    return SimpleNamespace(times=times,symbols=('A','B','IDX'),open=close-.1,
        high=close+1,low=close-1,close=close,volume=np.full_like(close,1000),
        tradable=np.array([True,True,False]),sector_by_symbol={'A':'IDX','B':'IDX'},
        holidays=frozenset([date(2023,1,26)]),nifty50_symbols=('A','B'))


def prefix(p,n):
    return SimpleNamespace(**{k:(v[:n] if k in ('times','open','high','low','close','volume') else v)
        for k,v in vars(p).items()})


def test_registry_frozen_and_counted():
    variants=load_variants()
    assert len(variants)==60
    assert len({v.id for v in variants})==60
    for family in range(1,9):
        assert 0<len([v for v in variants if v.family==family])<=30


@pytest.mark.parametrize('variant',load_variants(),ids=lambda v:v.id)
def test_all_targets_are_causal_long_only_and_bounded(variant):
    p=panel(hourly=variant.timeframe=='60minute')
    full=generate_targets(p,variant)
    cut=generate_targets(prefix(p,311),variant)
    np.testing.assert_allclose(full[:311],cut,equal_nan=True)
    assert np.all(full>=0) and np.all(full<=.1+1e-10)
    assert np.all(full.sum(axis=1)<=1+1e-10)
    assert np.all(full[:,2]==0)


def test_momentum_skips_last_month_and_ranks_with_symbol_ties():
    p=panel()
    p.close[-21:,0]=.1  # last-month collapse must not affect skip-month signal
    v=next(v for v in load_variants() if v.id=='F1_m63_top10')
    out=generate_targets(p,v)
    # At least one later month-end owns both valid stocks equally at capped 10%.
    assert np.any((out[:,0]==.1)&(out[:,1]==.1))


def test_gap_only_decides_after_first_hour_close():
    p=panel(n=30,hourly=True)
    p.close[:]=100; p.open[:]=100; p.high[:]=101; p.low[:]=99
    first=[]
    for i,t in enumerate(p.times):
        if i and t.date()!=p.times[i-1].date(): first.append(i)
    i=first[0]
    p.open[i,0]=103; p.close[i,0]=104
    v=next(v for v in load_variants() if v.id=='F7_go_gap2_hold1')
    out=generate_targets(p,v)
    assert out[i-1,0]==0
    assert out[i,0]==.1


def test_breakout_uses_previous_252_high_not_current_high():
    p=panel(n=300)
    p.high[:]=100; p.close[:]=99; p.open[:]=99
    p.close[270,0]=102;p.high[270,0]=104;p.volume[270,0]=3000
    v=next(v for v in load_variants() if v.id=='F2_vol125_ma100_hold5')
    out=generate_targets(p,v)
    assert out[269,0]==0
    assert np.all(out[270:275,0]==.1)
    assert out[275,0]==0


def test_calendar_never_trades_index_and_known_holiday_is_not_price_future():
    p=panel(n=400)
    v=next(v for v in load_variants() if v.id=='F8_preholiday_hold1')
    out=generate_targets(p,v)
    assert np.any(out[:,0]>.0)
    assert np.all(out[:,2]==0)


def test_wilder_rsi_known_answer():
    from orderflow.research.edge_strategies import _rsi
    result=_rsi(np.array([1.,2.,3.,2.,2.])[:,None],2)[:,0]
    np.testing.assert_allclose(result[2:],[100,50,50])


def test_strict_swing_cannot_break_before_right_hand_confirmation():
    from orderflow.research.edge_strategies import _structure
    p=panel(n=7)
    p.high[:,0]=[2,3,5,3,2,3,6]
    p.low[:,0]=[0,1,2,1,0,1,2]
    p.close[:,0]=[1,2,4,2,1,2,5.5]
    signals,breaks=_structure(p,2)
    assert not signals[:6,0].any()
    assert signals[6,0]
    short,_=_structure(prefix(p,4),2)
    assert not short[:,0].any()


def test_rank_ties_are_stable_and_cap_exposure():
    from orderflow.research.edge_strategies import _choose
    result=_choose(np.array([5.,5.,2.]),np.ones(3,bool),2)
    np.testing.assert_allclose(result,[.1,.1,0])


def test_known_month_end_and_week_end_decision_masks():
    from orderflow.research.edge_strategies import generate_rebalance_mask
    p=panel(n=30)
    monthly=next(v for v in load_variants() if v.family==1)
    weekly=next(v for v in load_variants() if v.family==5)
    zero=np.zeros_like(p.close)
    m=generate_rebalance_mask(p,monthly,zero)
    w=generate_rebalance_mask(p,weekly,zero)
    assert [p.times[i].date() for i in np.flatnonzero(m)]==[date(2022,1,31)]
    assert all(p.times[i].weekday()==4 for i in np.flatnonzero(w))


def test_sector_missing_reference_makes_signal_unavailable():
    p=panel(n=400);p.sector_by_symbol={}
    variant=next(v for v in load_variants() if v.family==5)
    assert not generate_targets(p,variant).any()


def test_known_calendar_turn_of_month_entry_rows():
    p=panel(n=30)
    variant=next(v for v in load_variants() if v.id=='F8_tom_m1_p1')
    out=generate_targets(p,variant)
    active=[p.times[i].date() for i in np.flatnonzero(out[:,0])]
    assert active==[date(2022,1,28),date(2022,1,31)]


def test_fixed_hold_exits_before_reentry_even_with_persistent_signal():
    from orderflow.research.edge_strategies import _fixed_holds
    p=panel(n=8)
    signals=np.zeros_like(p.close,dtype=bool);signals[:,0]=True
    out=_fixed_holds(p,signals,np.ones_like(p.close),2)
    np.testing.assert_allclose(out[:,0],[.1,.1,0,.1,.1,0,.1,.1])


def test_gap_missing_opening_hour_is_unavailable():
    p=panel(n=30,hourly=True)
    p.close[:]=100;p.open[:]=100
    first=next(i for i in range(1,len(p.times)) if p.times[i].date()!=p.times[i-1].date())
    # Remove the actual session-opening hour, then fabricate a later jump.
    for name in ('times','open','high','low','close','volume'):
        value=getattr(p,name)
        setattr(p,name,[v for i,v in enumerate(value) if i!=first] if name=='times' else np.delete(value,first,0))
    p.open[first,0]=103;p.close[first,0]=104
    variant=next(v for v in load_variants() if v.id=='F7_go_gap2_hold1')
    assert generate_targets(p,variant)[first,0]==0


def calendar_panel(start,n,events):
    p=panel(n=n)
    times=[];d=start
    while len(times)<n:
        if d.weekday()<5:times.append(datetime(d.year,d.month,d.day,3,45,tzinfo=timezone.utc))
        d+=timedelta(days=1)
    p.times=times;p.holiday_events=tuple(events)
    # Deliberately poison static set with FINAL dates; events must take priority.
    p.holidays=frozenset([date(2023,6,29),date(2024,1,22)])
    return p


def test_holiday_revision_does_not_rewrite_prior_preholiday_signal():
    events=[{'available_at_assumption':'2022-12-08T23:59:59+05:30',
        'add_regular_session_holidays':['2023-06-28'],'remove_regular_session_holidays':[]},
        {'available_at_assumption':'2023-06-27T23:59:59+05:30',
        'add_regular_session_holidays':['2023-06-29'],'remove_regular_session_holidays':['2023-06-28']}]
    p=calendar_panel(date(2023,6,23),6,events)
    variant=next(v for v in load_variants() if v.id=='F8_preholiday_hold1')
    out=generate_targets(p,variant)
    signals={stamp.date():out[i,0] for i,stamp in enumerate(p.times)}
    assert signals[date(2023,6,26)]==.1
    assert signals[date(2023,6,27)]==0
    np.testing.assert_allclose(out[:3],generate_targets(prefix(p,3),variant))


def test_late_announced_special_holiday_cannot_signal_before_announcement():
    events=[{'available_at_assumption':'2024-01-19T23:59:59+05:30',
        'add_regular_session_holidays':['2024-01-22'],'remove_regular_session_holidays':[]}]
    p=calendar_panel(date(2024,1,17),5,events)
    variant=next(v for v in load_variants() if v.id=='F8_preholiday_hold1')
    assert not generate_targets(p,variant).any()


def test_calendar_event_is_unavailable_until_actual_assumed_publication_time():
    from orderflow.research.edge_strategies import holidays_as_of
    events=[{'available_at_assumption':'2024-01-19T23:59:59+05:30',
        'add_regular_session_holidays':['2024-01-22'],'remove_regular_session_holidays':[]}]
    p=calendar_panel(date(2024,1,19),2,events)
    assert date(2024,1,22) not in holidays_as_of(p,0,'daily')
    assert date(2024,1,22) in holidays_as_of(p,1,'daily')


def test_monthly_rebalance_does_not_use_holiday_announced_after_that_close():
    from orderflow.research.edge_strategies import generate_rebalance_mask
    events=[{'available_at_assumption':'2023-09-28T23:59:59+05:30',
        'add_regular_session_holidays':['2023-09-29'],'remove_regular_session_holidays':[]}]
    p=calendar_panel(date(2023,9,27),5,events)
    p.holidays=frozenset([date(2023,9,29)])
    variant=next(v for v in load_variants() if v.family==1)
    mask=generate_rebalance_mask(p,variant,np.zeros_like(p.close))
    assert not mask[1]  # September28 close predates late announcement.


def test_hourly_calendar_uses_actual_bar_close_availability():
    from orderflow.research.edge_strategies import holidays_as_of
    p=panel(n=4,hourly=True)
    p.holiday_events=({'available_at_assumption':'2022-01-03T10:30:00+05:30',
        'add_regular_session_holidays':['2022-01-05'],'remove_regular_session_holidays':[]},)
    assert date(2022,1,5) not in holidays_as_of(p,0,'60minute') #10:15 close
    assert date(2022,1,5) in holidays_as_of(p,1,'60minute') #11:15 close


def test_breakout_zero_volume_never_counts_as_above_average_volume():
    p=panel(n=300)
    p.high[:]=100;p.close[:]=99;p.open[:]=99;p.volume[:]=0
    p.close[270,0]=102;p.high[270,0]=104
    variant=next(v for v in load_variants() if v.id=='F2_vol125_ma100_hold5')
    assert not generate_targets(p,variant).any()
