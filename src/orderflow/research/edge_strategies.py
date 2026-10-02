"""Frozen EXPLORATORY, long-only delivery signals available only at bar close.

Signals are target weights, not orders. Execution must lag targets to the NEXT bar
open. Rolling quantities use the current/past bars only; confirmed swings become
usable after their right-hand confirmation bars close. Calendar information is
known ex ante and never inferred from the final downloaded price sample.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import calendar
import json
from pathlib import Path
from typing import Any

import numpy as np


from .edge_types import StrategyVariant


def load_variants(path: str | Path | None = None) -> tuple[StrategyVariant,...]:
    """Load all 60 predeclared variants; every declared variant counts as a trial."""
    source=Path(path) if path else Path(__file__).resolve().parents[3]/'config/edge_scout_variants.json'
    raw=json.loads(source.read_text())
    return tuple(StrategyVariant(**v) for v in raw['variants'])


def _dates(panel):
    result=[]
    for t in panel.times:
        if hasattr(t,'to_pydatetime'): t=t.to_pydatetime()
        if isinstance(t,np.datetime64):
            t=datetime.fromisoformat(np.datetime_as_string(t,unit='s'))
        # Canonical daily/hour timestamps UTC; decisions use Indian session dates.
        if getattr(t,'tzinfo',None) is not None:
            from zoneinfo import ZoneInfo
            t=t.astimezone(ZoneInfo('Asia/Kolkata'))
        result.append(t.date() if hasattr(t,'date') else t)
    return result


def _shift(x,n):
    out=np.full_like(x,np.nan,dtype=float)
    if n: out[n:]=x[:-n]
    else: out[:]=x
    return out


def _rolling(x,n,kind='mean'):
    """Trailing n observations with a full finite window; never forward fill."""
    out=np.full_like(x,np.nan,dtype=float)
    if len(x)<n:return out
    view=np.lib.stride_tricks.sliding_window_view(x,n,axis=0)
    valid=np.isfinite(view).all(axis=-1)
    with np.errstate(invalid='ignore'):
        fn={'mean':np.mean,'std':lambda a,axis:np.std(a,axis=axis,ddof=1),'max':np.max}[kind]
        values=fn(view,axis=-1)
    out[n-1:]=np.where(valid,values,np.nan)
    return out


def _rsi(close,period):
    """Wilder RSI seeded from the first period consecutive finite changes."""
    delta=close-_shift(close,1); out=np.full_like(close,np.nan)
    gain=np.full(close.shape[1],np.nan); loss=gain.copy(); streak=np.zeros(close.shape[1],int)
    for i in range(1,len(close)):
        ok=np.isfinite(delta[i]); streak=np.where(ok,streak+1,0)
        gain=np.where(ok,gain,np.nan);loss=np.where(ok,loss,np.nan)
        seed=ok&(streak==period)
        if np.any(seed):
            recent=delta[i-period+1:i+1]
            gain[seed]=np.maximum(recent[:,seed],0).mean(0)
            loss[seed]=np.maximum(-recent[:,seed],0).mean(0)
        update=ok&(streak>period)
        gain[update]=(gain[update]*(period-1)+np.maximum(delta[i,update],0))/period
        loss[update]=(loss[update]*(period-1)+np.maximum(-delta[i,update],0))/period
        usable=streak>=period
        with np.errstate(divide='ignore',invalid='ignore'):
            values=100-100/(1+gain/loss)
        values=np.where(loss==0,np.where(gain==0,50,100),values)
        out[i]=np.where(usable,values,np.nan)
    return out



def _decision_close(panel,row,timeframe):
    """Timestamp when a close signal exists, including final partial hour."""
    from zoneinfo import ZoneInfo
    stamp=panel.times[row]
    if hasattr(stamp,'to_pydatetime'):stamp=stamp.to_pydatetime()
    if isinstance(stamp,np.datetime64):
        raise ValueError('calendar decisions require timezone-aware timestamps')
    if stamp.tzinfo is None:raise ValueError('calendar decisions require timezone-aware timestamps')
    local=stamp.astimezone(ZoneInfo('Asia/Kolkata'))
    session_close=local.replace(hour=15,minute=30,second=0,microsecond=0)
    return session_close if timeframe=='daily' else min(local+timedelta(hours=1),session_close)


def _holiday_schedule(panel,timeframe):
    """Replay only already-published calendar amendments at each decision close.

    When event history is supplied, the static final holiday set is ignored.
    Legacy simulator panels without events may supply known-ex-ante holidays.
    """
    events=getattr(panel,'holiday_events',())
    if not events:return [frozenset(panel.holidays)]*len(panel.times)
    prepared=[]
    for event in events:
        available=datetime.fromisoformat(event['available_at_assumption'])
        if available.tzinfo is None:raise ValueError('holiday event availability must be timezone-aware')
        add={date.fromisoformat(d) if isinstance(d,str) else d for d in event.get('add_regular_session_holidays',())}
        remove={date.fromisoformat(d) if isinstance(d,str) else d for d in event.get('remove_regular_session_holidays',())}
        prepared.append((available,add,remove))
    prepared.sort(key=lambda event:event[0])
    result=[];known=set();cursor=0;snapshot=frozenset()
    for row in range(len(panel.times)):
        close=_decision_close(panel,row,timeframe)
        changed=False
        while cursor<len(prepared) and prepared[cursor][0]<=close:
            _,add,remove=prepared[cursor]
            known.difference_update(remove);known.update(add)
            cursor+=1;changed=True
        if changed:snapshot=frozenset(known)
        result.append(snapshot)
    return result


def holidays_as_of(panel,row,timeframe='daily'):
    """Announced regular-session holidays available by this observed close."""
    return _holiday_schedule(panel,timeframe)[row]

def _session(d,holidays): return d.weekday()<5 and d not in holidays

def _next_session(d,holidays):
    d+=timedelta(days=1)
    while not _session(d,holidays):d+=timedelta(days=1)
    return d

def _previous_session(d,holidays):
    d-=timedelta(days=1)
    while not _session(d,holidays):d-=timedelta(days=1)
    return d


def _choose(score,valid,top):
    candidates=np.flatnonzero(valid&np.isfinite(score))
    chosen=candidates[np.argsort(-score[candidates],kind='stable')[:top]]
    weights=np.zeros(len(score));weights[chosen]=min(.1,1/top)
    return weights


def _fixed_holds(panel,signals,scores,hold,breaks=None,hold_days=False):
    """Keep each selected close signal for H bars/dates, up to 10 names at 10%.

    Expiration/structure-break rows cannot immediately reenter: at least one
    close decision is flat, so an actual next-open exit is charged its costs."""
    t,n=signals.shape; out=np.zeros((t,n));remaining=np.zeros(n,int)
    dates=_dates(panel)
    for i in range(t):
        decrement=not hold_days or i==0 or dates[i]!=dates[i-1]
        expired=(remaining==1) if decrement else np.zeros(n,bool)
        if decrement: remaining=np.maximum(remaining-1,0)
        if breaks is not None:
            expired |= breaks[i]
            remaining=np.where(breaks[i],0,remaining)
        invalid=~np.isfinite(panel.close[i])|~panel.tradable
        remaining[invalid]=0
        free=max(0,10-np.count_nonzero(remaining))
        valid=signals[i]&~invalid&~expired&(remaining==0)
        selected=np.flatnonzero(_choose(scores[i],valid,free)>0) if free else np.array([],int)
        remaining[selected]=hold
        # Fixed 10% per name with gross-exposure cap: <=10 names ultimately.
        active=np.flatnonzero(remaining>0)
        if len(active)>10:
            # Preserve original older positions before deterministic new ranking.
            newly=set(selected.tolist());old=[j for j in active if j not in newly]
            keep=old+[j for j in selected if j not in old][:max(0,10-len(old))]
            drop=np.setdiff1d(active,keep);remaining[drop]=0;active=np.array(keep,int)
        out[i,active]=.1
    return out


def _structure(panel,n):
    """Strict fractal swings confirmed at pivot+n; crossing confirmed high is BOS/CHoCH.

    A bullish close crossing the most recently confirmed high enters regardless
    of prior bullish/bearish state (BOS or CHoCH respectively). A close below the
    most recently confirmed low is the structure-break exit. Ties are not pivots.
    """
    close=panel.close; t,m=close.shape
    latest_high=np.full(m,np.nan);latest_low=np.full(m,np.nan)
    signals=np.zeros((t,m),bool);breaks=signals.copy()
    for i in range(t):
        if i>=2*n:
            pivot=i-n; hi=panel.high[pivot];lo=panel.low[pivot]
            neighbors=np.concatenate((panel.high[pivot-n:pivot],panel.high[pivot+1:i+1]),0)
            low_neighbors=np.concatenate((panel.low[pivot-n:pivot],panel.low[pivot+1:i+1]),0)
            hp=np.isfinite(hi)&np.isfinite(neighbors).all(0)&(hi>np.max(neighbors,0))
            lp=np.isfinite(lo)&np.isfinite(low_neighbors).all(0)&(lo<np.min(low_neighbors,0))
            latest_high=np.where(hp,hi,latest_high);latest_low=np.where(lp,lo,latest_low)
        if i:
            signals[i]=(close[i]>latest_high)&(close[i-1]<=latest_high)
            breaks[i]=(close[i]<latest_low)&(close[i-1]>=latest_low)
    return signals,breaks


def generate_targets(panel,variant:StrategyVariant,daily_reference=None)->np.ndarray:
    """Return T×N close-available target weights; no index is tradable.

    Whole families use fixed predeclared rules. No parameter is estimated using
    an out-of-sample return. Missing observations make signals unavailable.
    daily_reference is reserved for caller metadata and not required by signals.
    """
    c=np.asarray(panel.close,float); p=variant.parameters;f=variant.family
    dates=_dates(panel);holiday_schedule=_holiday_schedule(panel,variant.timeframe)
    tradable=np.asarray(panel.tradable,bool); valid=np.isfinite(c)&tradable[None,:]
    out=np.zeros_like(c);t,n=c.shape
    if f in (1,5,6):
        if f==1:
            score=_shift(c,p['skip'])/_shift(c,p['skip']+p['lookback'])-1
        elif f==5:
            returns=c/_shift(c,p['lookback'])-1;score=np.full_like(c,np.nan)
            symbol_index={s:i for i,s in enumerate(panel.symbols)}
            for j,symbol in enumerate(panel.symbols):
                benchmark=panel.sector_by_symbol.get(symbol)
                if benchmark in symbol_index:score[:,j]=returns[:,j]-returns[:,symbol_index[benchmark]]
        else:
            returns=c/_shift(c,1)-1;score=-_rolling(returns,p['lookback'],'std')
        current=np.zeros(n)
        for i,d in enumerate(dates):
            holidays=holiday_schedule[i]
            next_d=_next_session(d,holidays)
            rebalance=next_d.month!=d.month if f==1 else next_d.isocalendar()[:2]!=d.isocalendar()[:2]
            if rebalance:current=_choose(score[i],valid[i],p['top'])
            current=np.where(valid[i],current,0)
            out[i]=current
        return out
    if f==2:
        previous_high=_rolling(_shift(panel.high,1),p['lookback'],'max')
        avgvol=_rolling(_shift(panel.volume,1),p['volume_window'])
        trend=_rolling(c,p['trend'])
        signal=(c>previous_high)&(avgvol>0)&(panel.volume>0)&(panel.volume>=p['volume_multiple']*avgvol)&(c>trend)
        return _fixed_holds(panel,signal,c/previous_high-1,p['hold'])
    if f==3:
        rsi=_rsi(c,p['rsi_period']);trend=_rolling(c,p['trend'])
        signal=(rsi<p['threshold'])&(c>trend)
        return _fixed_holds(panel,signal,100-rsi,p['hold'])
    if f==4:
        signal,breaks=_structure(panel,p['swing'])
        return _fixed_holds(panel,signal,c/_shift(c,1)-1,p['hold_days'],breaks,hold_days=True)
    if f==7:
        signals=np.zeros_like(c,bool);scores=np.full_like(c,np.nan)
        from zoneinfo import ZoneInfo
        daily_lookup={}
        if daily_reference is not None:
            daily_dates=_dates(daily_reference)
            daily_columns={symbol:j for j,symbol in enumerate(daily_reference.symbols)}
            for row,d in enumerate(daily_dates):
                daily_lookup[d]=np.array([daily_reference.close[row,daily_columns[symbol]] if symbol in daily_columns else np.nan for symbol in panel.symbols])
        for i in range(1,t):
            if dates[i]==dates[i-1]:continue
            stamp=panel.times[i]
            if hasattr(stamp,'to_pydatetime'):stamp=stamp.to_pydatetime()
            local=stamp.astimezone(ZoneInfo('Asia/Kolkata'))
            if (local.hour,local.minute)!=(9,15):continue
            previous_day=_previous_session(dates[i],holiday_schedule[i])
            if daily_reference is not None:
                previous_close=daily_lookup.get(previous_day,np.full(n,np.nan))
            else:
                previous_stamp=panel.times[i-1]
                if hasattr(previous_stamp,'to_pydatetime'):previous_stamp=previous_stamp.to_pydatetime()
                previous_local=previous_stamp.astimezone(ZoneInfo('Asia/Kolkata'))
                if dates[i-1]!=previous_day or (previous_local.hour,previous_local.minute)!=(15,15):continue
                previous_close=c[i-1]
            gap=panel.open[i]/previous_close-1
            signal=(gap>p['gap']) if p['side']=='go' else (gap<-p['gap'])
            signals[i]=signal&(c[i]>panel.open[i]);scores[i]=np.abs(gap)
        return _fixed_holds(panel,signals,scores,p['hold_days'],hold_days=True)
    if f==8:
        n50=set(panel.nifty50_symbols);mask=tradable&np.array([s in n50 for s in panel.symbols])
        if p['effect']=='preholiday':
            signals=np.zeros_like(c,bool)
            for i,d in enumerate(dates):
                holidays=holiday_schedule[i]
                decision_dates={_previous_session(_previous_session(h,holidays),holidays) for h in holidays if h.weekday()<5 and h>d}
                if d in decision_dates:signals[i]=mask
            # Equal-weight current Nifty50 constituent basket, a survivorship proxy.
            remaining=0
            for i in range(t):
                remaining=max(0,remaining-1)
                if np.any(signals[i]):remaining=p['hold']
                if remaining:
                    candidates=np.flatnonzero(mask&valid[i])
                    if len(candidates):out[i,candidates]=min(.1,1/len(candidates))
            return out
        for i,d in enumerate(dates):
            holidays=holiday_schedule[i]
            entry_day=_next_session(d,holidays)
            month_first=date(entry_day.year,entry_day.month,1)
            while not _session(month_first,holidays):month_first+=timedelta(days=1)
            # Determine signed session position around current and next month.
            active=False
            for anchor in (month_first,_next_month_first(entry_day,holidays)):
                before=[];b=anchor
                for k in range(p['before']):b=_previous_session(b,holidays);before.append(b)
                after=[];a=anchor
                for k in range(p['after']):after.append(a);a=_next_session(a,holidays)
                if entry_day in before+after:active=True
            if active:
                candidates=np.flatnonzero(mask&valid[i]);out[i,candidates]=min(.1,1/len(candidates)) if len(candidates) else 0
        return out
    raise ValueError(f'Unknown strategy family {f}')


def _next_month_first(d,holidays):
    first=date(d.year+int(d.month==12),1 if d.month==12 else d.month+1,1)
    while not _session(first,holidays):first+=timedelta(days=1)
    return first


def generate_rebalance_mask(panel,variant:StrategyVariant,weights:np.ndarray)->np.ndarray:
    """Close decision dates, including unchanged monthly/weekly target baskets.

    Engine executes each true decision at the next observed bar open. Other
    families rebalance only when the target vector changes; repeating unchanged
    targets does not create unsolicited daily portfolio rebalancing.
    """
    mask=np.zeros(len(weights),bool)
    if len(weights):
        mask[0]=np.any(weights[0]!=0)
        mask[1:]=np.any(np.abs(weights[1:]-weights[:-1])>1e-12,axis=1)
    dates=_dates(panel);holiday_schedule=_holiday_schedule(panel,variant.timeframe)
    if variant.family in (1,5,6):
        for i,d in enumerate(dates):
            after=_next_session(d,holiday_schedule[i])
            scheduled=after.month!=d.month if variant.family==1 else after.isocalendar()[:2]!=d.isocalendar()[:2]
            mask[i] |= scheduled
    return mask
