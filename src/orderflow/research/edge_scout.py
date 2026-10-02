"""EXPLORATORY rolling walk-forward scout; public candles, never broker execution."""
from __future__ import annotations
import argparse
from dataclasses import replace
from datetime import date
import hashlib
import json
from pathlib import Path
import time
import numpy as np
import pandas as pd
from .edge_types import MarketPanel
from .edge_engine import BacktestResult, CostModel, PortfolioLimits, backtest, summarize, regime_metrics
from .edge_strategies import load_variants, generate_targets, generate_rebalance_mask

FAMILIES={1:'Cross-sectional momentum',2:'52-week-high breakout',3:'Short-term mean reversion',4:'Swing BOS/CHoCH',5:'Sector relative strength',6:'Low-volatility tilt',7:'Gap-and-go / gap-fade',8:'Calendar effects'}


def select_variant(training_summaries:dict,*,min_trades:int=30)->str|None:
    """Choose maximum training after-cost Sharpe only; stable ID breaks ties."""
    eligible=[(float(row['sharpe']),name) for name,row in training_summaries.items()
              if row.get('sharpe') is not None and np.isfinite(row['sharpe']) and row.get('trades',0)>=min_trades]
    return sorted(eligible,key=lambda item:(-item[0],item[1]))[0][1] if eligible else None


def select_fold(training_summaries:dict,available_oos:set[str])->tuple[str|None,bool]:
    """Future missing execution data may invalidate, never change, a train winner."""
    winner=select_variant(training_summaries)
    return winner,winner is not None and winner in available_oos


def slice_panel(panel:MarketPanel,start:pd.Timestamp,end:pd.Timestamp)->MarketPanel:
    """Half-open aware time slice preserving observation NaNs and metadata."""
    if start.tz is None or end.tz is None:raise ValueError('slice bounds must be aware')
    mask=(panel.times>=start)&(panel.times<end)
    return replace(panel,times=panel.times[mask],**{name:getattr(panel,name)[mask] for name in ('open','high','low','close','volume')})


def load_panel(cache_dir:str|Path,timeframe:str,*,holiday_file:str|Path|None=None)->MarketPanel:
    """Nifty50 observed session grid; no future fill, no invented stock/index bars.

    Historical daily API timestamps vary; session_date is authoritative for the
    daily grid. Vendor raw timestamps are preserved in the ignored raw cache.
    Regular-hours hourly slots exclude separately retained special sessions.
    """
    cache=Path(cache_dir)
    import pyarrow.parquet as pq
    path=cache/f'candles_{timeframe}.parquet'
    columns=['symbol','ts','session_date','open','high','low','close','volume']
    if 'quality_flags' in pq.read_schema(path).names:columns.append('quality_flags')
    df=pd.read_parquet(path,columns=columns)
    if 'quality_flags' in df:
        ambiguous=df.quality_flags.map(lambda flags:flags is not None and 'CONFLICTING_DUPLICATE_CANDLE' in flags)
        df.loc[ambiguous,['open','high','low','close','volume']]=np.nan
    df['ts']=pd.to_datetime(df['ts'],utc=True)
    if timeframe=='daily':df['ts']=pd.to_datetime(df['session_date'].astype(str)).dt.tz_localize('Asia/Kolkata').dt.tz_convert('UTC')+pd.Timedelta(hours=9,minutes=15)
    else:
        local=df['ts'].dt.tz_convert('Asia/Kolkata');minutes=local.dt.hour*60+local.dt.minute
        df=df[(minutes>=555)&(minutes<930)&(local.dt.minute==15)]
    # Regular weekday sessions only; weekend special trading is retained raw.
    df=df[df['ts'].dt.tz_convert('Asia/Kolkata').dt.weekday<5]
    if df.duplicated(['ts','symbol']).any():raise ValueError('duplicate symbol bars require explicit upstream audit')
    grid=pd.DatetimeIndex(df.loc[df.symbol=='NIFTY_50','ts'].sort_values().unique())
    universe=pd.read_csv(cache/'universe.csv')
    stocks=set(universe.symbol)
    symbols=tuple(sorted(set(df.symbol)|stocks))
    arrays={name:df.pivot(index='ts',columns='symbol',values=name).reindex(index=grid,columns=symbols).to_numpy(dtype=float)
            for name in ('open','high','low','close','volume')}
    holiday_dates=set();holiday_events=();holiday_years=frozenset()
    if holiday_file and Path(holiday_file).exists():
        record=json.loads(Path(holiday_file).read_text())
        holiday_events=tuple(record.get('events',[]))
        holiday_years=frozenset(record.get('calendar_years_certified',[]))
        # Static fallback contains annual announcements only; revisions are
        # applied by the signal engine strictly as of each decision close.
        for source in record.get('annual_sources',[]):
            holiday_dates.update(date.fromisoformat(item) for item in source['announced_weekday_holidays'])
        special={date.fromisoformat(source['muhurat_special_session_date']) for source in record.get('annual_sources',[]) if source.get('muhurat_special_session_date')}
        keep=np.array([stamp.tz_convert('Asia/Kolkata').date() not in special for stamp in grid])
        grid=grid[keep];arrays={name:value[keep] for name,value in arrays.items()}
    member_column='nifty50' if 'nifty50' in universe else 'is_nifty50'
    members=tuple(universe.loc[universe[member_column].astype(str).str.lower()=='true','symbol']) if member_column in universe else ()
    return MarketPanel(grid,symbols,**arrays,tradable=np.array([symbol in stocks for symbol in symbols]),
        sector_by_symbol=dict(zip(universe.symbol,universe.sector_index)),holidays=frozenset(holiday_dates),nifty50_symbols=members,holiday_events=holiday_events,holiday_years=holiday_years)


def _bounds(year:int)->pd.Timestamp:
    return pd.Timestamp(year=year,month=1,day=1,tz='Asia/Kolkata').tz_convert('UTC')


def _fold_result(panel,weights,mask,start,end,limits)->BacktestResult:
    """Flat fold with an observed preceding close to permit first-test-open entry."""
    first=int(panel.times.searchsorted(start));last=int(panel.times.searchsorted(end))
    if last-first<2:raise ValueError('insufficient fold observations')
    begin=max(0,first-1)
    subset=replace(panel,times=panel.times[begin:last],**{name:getattr(panel,name)[begin:last] for name in ('open','high','low','close','volume')})
    targets=weights[begin:last];rebalance=mask[begin:last].copy()
    # A fresh portfolio may adopt the known preceding-close allocation once.
    if begin<first:rebalance[0]=True
    result=backtest(subset,targets,CostModel(),limits,rebalance_mask=rebalance)
    result.returns=result.returns[result.returns.index>=start]
    result.equity=result.equity[result.equity.index>=start]
    if result.audit['terminal_unliquidated_positions']:raise ValueError('fold cannot be declared flat: missing terminal opens')
    return result


def _combine(results:list[BacktestResult])->BacktestResult:
    if not results:return BacktestResult(pd.Series(dtype=float,index=pd.DatetimeIndex([],tz='UTC')),pd.Series(dtype=float),pd.DataFrame(),pd.DataFrame(),{})
    returns=pd.concat([result.returns for result in results]).sort_index()
    if returns.index.has_duplicates:raise ValueError('overlapping OOS folds')
    trades=pd.concat([result.trades for result in results],ignore_index=True)
    orders=pd.concat([result.orders for result in results],ignore_index=True)
    return BacktestResult(returns,1e6*(1+returns).cumprod(),trades,orders,{'folds':len(results)})



def _cache_result(folder:Path,result:BacktestResult|None=None)->BacktestResult:
    """Private research cache uses explicit tables/JSON, never pickle objects."""
    if result is not None:
        folder.mkdir(parents=True,exist_ok=True)
        result.returns.rename('return').to_frame().to_parquet(folder/'returns.parquet')
        result.trades.to_parquet(folder/'trades.parquet',index=False)
        result.orders.to_parquet(folder/'orders.parquet',index=False)
        (folder/'audit.json').write_text(json.dumps(result.audit,allow_nan=False,default=str))
        return result
    returns=pd.read_parquet(folder/'returns.parquet')['return']
    return BacktestResult(returns,1e6*(1+returns).cumprod(),pd.read_parquet(folder/'trades.parquet'),pd.read_parquet(folder/'orders.parquet'),json.loads((folder/'audit.json').read_text()))


def _fingerprint(cache_dir:Path,timeframe:str,holiday_file:Path)->str:
    """Invalidate completed research caches when data, rules or costs change."""
    digest=hashlib.sha256()
    files=[cache_dir/f'candles_{timeframe}.parquet',cache_dir/'universe.csv',Path('config/edge_scout_variants.json'),holiday_file]
    files += [Path(__file__).with_name(name) for name in ('edge_scout.py','edge_engine.py','edge_strategies.py','edge_types.py')]
    for path in files:
        if path.exists():
            with path.open('rb') as handle:
                while chunk:=handle.read(1024*1024):digest.update(chunk)
    return digest.hexdigest()


def run_study(cache_dir:str|Path,*,output_dir:str|Path,include_hourly:bool=True,holiday_file:str|Path='docs/EDGE_SCOUT_HOLIDAYS.json')->dict:
    """Register all trials; fit only three prior years, evaluate disjoint next years.

    Rankings use the complete common 2025 OOS year; full available daily OOS history is
    supplementary. Each fold starts with INR1m cash and exits at its final open.
    Calendar constituent baskets allow50 positions; other families allow20.
    """
    started=time.monotonic();output=Path(output_dir);output.mkdir(parents=True,exist_ok=True)
    daily=load_panel(cache_dir,'daily',holiday_file=holiday_file)
    hourly=load_panel(cache_dir,'hourly',holiday_file=holiday_file) if include_hourly else None
    variants=load_variants();trials=len(variants);variant_by_id={v.id:v for v in variants}
    panels={'daily':daily,'60minute':hourly}
    fingerprints={'daily':_fingerprint(Path(cache_dir),'daily',Path(holiday_file))}
    if hourly is not None:fingerprints['60minute']=_fingerprint(Path(cache_dir),'hourly',Path(holiday_file))
    weights={};masks={};failures=[];train={};test={};ledger=[];evaluated_ids=[]
    end_year=daily.times.tz_convert('Asia/Kolkata').year.max()
    observed_stock_dates=daily.times[np.isfinite(daily.close[:,daily.tradable]).any(axis=1)]
    earliest=max(2000,int(observed_stock_dates.tz_convert('Asia/Kolkata').year.min()))
    for variant in variants:
        panel=panels.get(variant.timeframe)
        if panel is None:
            ledger.append({'variant':variant.id,'status':'DEFERRED_HOURLY_DOWNLOAD','family':variant.family});continue
        if variant.family==8 and variant.parameters.get('effect')=='preholiday' and not panel.holidays:
            ledger.append({'variant':variant.id,'status':'NOT_TESTABLE_NO_ANNOUNCED_CALENDAR','family':variant.family});continue
        weights[variant.id]=generate_targets(panel,variant,daily_reference=daily)
        masks[variant.id]=generate_rebalance_mask(panel,variant,weights[variant.id])
        min_test=max(earliest+3,2025 if variant.timeframe=='60minute' else earliest+3)
        for year in range(min_test,int(end_year)+1):
            # Pre-holiday tests require a complete three-year known calendar.
            if variant.family==8 and variant.parameters.get('effect')=='preholiday' and year<2025:continue
            limits=PortfolioLimits(max_positions=50 if variant.family==8 else 20)
            key=(variant.id,year)
            try:
                checkpoint=output/'checkpoints'/fingerprints[variant.timeframe]/variant.id/str(year)
                metrics_path=checkpoint/'training.json'
                if metrics_path.exists() and (checkpoint/'test'/'audit.json').exists():
                    train[key]=json.loads(metrics_path.read_text());test[key]=_cache_result(checkpoint/'test')
                else:
                    result=_fold_result(panel,weights[variant.id],masks[variant.id],_bounds(year-3),_bounds(year),limits)
                    train[key]=summarize(result,trials)
                    test[key]=_fold_result(panel,weights[variant.id],masks[variant.id],_bounds(year),_bounds(year+1),limits)
                    checkpoint.mkdir(parents=True,exist_ok=True)
                    metrics_path.write_text(json.dumps(train[key],allow_nan=False,default=str))
                    _cache_result(checkpoint/'test',test[key])
            except ValueError as exc:
                failures.append({'variant':variant.id,'test_year':year,'reason':str(exc)})
        evaluated_ids.append(variant.id)
        del weights[variant.id],masks[variant.id]
        ledger.append({'variant':variant.id,'family':variant.family,'timeframe':variant.timeframe,'parameters':dict(variant.parameters),'status':'EVALUATED','valid_oos_folds':sum(k[0]==variant.id for k in test)})
        print(json.dumps({'variant':variant.id,'folds':sum(k[0]==variant.id for k in test),'elapsed_s':round(time.monotonic()-started,2)}),flush=True)
    selections=[];selected={family:[] for family in FAMILIES};common={family:[] for family in FAMILIES};partial={family:[] for family in FAMILIES}
    for family in FAMILIES:
        candidates=[variant.id for variant in variants if variant.family==family]
        for year in range(earliest+3,int(end_year)+1):
            summaries={vid:train[(vid,year)] for vid in candidates if (vid,year) in train}
            winner,valid=select_fold(summaries,{vid for vid in candidates if (vid,year) in test})
            if winner is None:continue
            selections.append({'family':family,'test_year':year,'selected_variant':winner,'train_sharpe':summaries[winner]['sharpe'],'train_trades':summaries[winner]['trades'],'test_valid':valid})
            if not valid:
                failures.append({'variant':winner,'test_year':year,'family':family,'reason':'SELECTED_TRAIN_WINNER_HAS_INVALID_OOS; no substitution'})
                continue
            result=test[(winner,year)]
            if year<end_year:selected[family].append(result)
            else:partial[family].append(result)
            if year==2025:common[family].append(result)

    # All trial Sharpe values on the same common OOS period supply DSR scale.
    trial_sharpes=[];trial_results={}
    for vid in evaluated_ids:
        results=[result for (name,year),result in test.items() if name==vid and year==2025]
        if results:
            stats=summarize(_combine(results),trials);trial_results[vid]=stats
            if stats['sharpe'] is not None:trial_sharpes.append(stats['sharpe'])
    index=daily.symbols.index('NIFTY_50');benchmark=pd.Series(daily.close[:,index],index=daily.times)
    family_results=[]
    for family,name in FAMILIES.items():
        result=_combine(common[family]);extended=_combine(selected[family])
        stats=summarize(result,trials,trial_sharpes) if len(result.returns) else None
        full=summarize(extended,trials,trial_sharpes) if len(extended.returns) else None
        family_results.append({'family':family,'name':name,'common_oos':stats,'extended_oos':full,'partial_2026':summarize(_combine(partial[family]),trials,trial_sharpes) if partial[family] else None,'regimes':regime_metrics(result,benchmark) if stats else {},'common_start':str(result.returns.index.min()) if stats else None,'common_end':str(result.returns.index.max()) if stats else None})
        if stats:
            result.returns.to_csv(output/f'family_{family}_oos_returns.csv')
            result.trades.to_parquet(output/f'family_{family}_oos_trades.parquet',index=False)
    payload={'label':'EXPLORATORY','registry_sha256':hashlib.sha256(Path('config/edge_scout_variants.json').read_bytes()).hexdigest(),'registered_trials':trials,'research_cache_fingerprints':fingerprints,'families':family_results,'selections':selections,'variants':ledger,'variant_common_oos':trial_results,'failed_folds':failures,'elapsed_seconds':time.monotonic()-started,'primary_window':'2025-01-01 through 2025-12-31 complete common OOS year; 2026 separately partial','selection_rule':'maximum preceding3-calendar-year after-cost Sharpe; >=30 realized lot fragments; stable ID ties','initial_fold_capital':1e6,'costs':CostModel().__dict__}
    path=output/'results.json';path.write_text(json.dumps(payload,indent=2,allow_nan=False,default=str))
    return payload


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache',default='data/edge_scout');parser.add_argument('--output',default='data/edge_scout/results');parser.add_argument('--daily-only',action='store_true')
    args=parser.parse_args();run_study(args.cache,output_dir=args.output,include_hourly=not args.daily_only)

if __name__=='__main__':main()
