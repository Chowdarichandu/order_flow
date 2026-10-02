"""Known-answer integration guards for EXPLORATORY walk-forward research."""
from datetime import date
import numpy as np
import pandas as pd
import pytest
from orderflow.research.edge_types import MarketPanel
from orderflow.research.edge_scout import select_variant, slice_panel, load_panel


def panel():
    times=pd.date_range('2020-01-01',periods=6,tz='UTC')
    values=np.arange(12,dtype=float).reshape(6,2)+100
    return MarketPanel(times,('A','NIFTY_50'),values,values,values,values,values,np.array([True,False]),{'A':'NIFTY_50'})


def test_selector_only_uses_supplied_training_metrics_and_stable_ties():
    summaries={'b':{'sharpe':1.0,'trades':40},'a':{'sharpe':1.0,'trades':40},'z':{'sharpe':10.0,'trades':2}}
    assert select_variant(summaries,min_trades=30)=='a'
    assert select_variant({'a':{'sharpe':float('nan'),'trades':100}},min_trades=30) is None
    assert summaries['z']['sharpe']==10


def test_slice_retains_only_requested_times_without_rebasing_arrays():
    original=panel();subset=slice_panel(original,pd.Timestamp('2020-01-02',tz='UTC'),pd.Timestamp('2020-01-05',tz='UTC'))
    assert len(subset.times)==3
    assert np.array_equal(subset.open,original.open[1:4])
    assert subset.sector_by_symbol==original.sector_by_symbol
    with pytest.raises(ValueError):slice_panel(original,pd.Timestamp('2020-01-01'),pd.Timestamp('2020-01-05'))


def test_loader_uses_nifty_session_grid_keeps_missing_nan_and_never_trades_indices(tmp_path):
    # Third party grid values cannot create a synthetic stock/benchmark session.
    pd.DataFrame([{'symbol':'A','instrument_key':'NSE_EQ|A','industry':'X','sector_index':'NIFTY_50','is_nifty50':True}]).to_csv(tmp_path/'universe.csv',index=False)
    rows=[]
    for symbol,day,price in [('NIFTY_50','2020-01-02',100),('NIFTY_50','2020-01-03',101),('A','2020-01-02',10),('A','2020-01-04',99)]:
        rows.append(dict(symbol=symbol,ts=pd.Timestamp(day,tz='Asia/Kolkata'),session_date=pd.Timestamp(day).date(),open=price,high=price,low=price,close=price,volume=10))
    pd.DataFrame(rows).to_parquet(tmp_path/'candles_daily.parquet',index=False)
    result=load_panel(tmp_path,'daily')
    a=result.symbols.index('A');idx=result.symbols.index('NIFTY_50')
    assert len(result.times)==2 and np.isnan(result.open[1,a])
    assert result.tradable[a] and not result.tradable[idx]
    assert result.nifty50_symbols==('A',)


def test_conflicting_candle_is_a_missing_observation_not_an_execution_price(tmp_path):
    pd.DataFrame([{'symbol':'A','instrument_key':'NSE_EQ|A','sector_index':'NIFTY_50','nifty50':True}]).to_csv(tmp_path/'universe.csv',index=False)
    rows=[]
    for symbol,flags in [('NIFTY_50',[]),('A',['CONFLICTING_DUPLICATE_CANDLE'])]:
        rows.append(dict(symbol=symbol,ts=pd.Timestamp('2020-01-02',tz='Asia/Kolkata'),session_date=date(2020,1,2),open=10,high=10,low=10,close=10,volume=10,quality_flags=flags))
    pd.DataFrame(rows).to_parquet(tmp_path/'candles_daily.parquet',index=False)
    result=load_panel(tmp_path,'daily')
    assert np.isnan(result.open[0,result.symbols.index('A')])
    assert result.times[0].tz_convert('Asia/Kolkata').hour==9
    assert result.times[0].tz_convert('Asia/Kolkata').minute==15


def test_verdict_requires_after_cost_edge_and_longer_oos_support():
    from orderflow.research.edge_report import classify_family
    common=dict(cagr=.1,sharpe=1,deflated_sharpe_probability=.99,trades=200,average_move_pct=2,average_cost_pct=.5)
    extended=dict(cagr=.08,sharpe=.8,annual_returns={'2020':.1,'2021':.1,'2022':-.02,'2023':.1})
    assert classify_family(common,extended)=='PROMISING'
    assert classify_family(dict(common,cagr=-.01),extended)=='NO EDGE'
    assert classify_family(dict(common,deflated_sharpe_probability=.5),extended)=='WEAK'
    assert classify_family(common,dict(extended,annual_returns={'2025':.1}))=='WEAK'


def test_failed_future_fold_never_changes_the_training_winner():
    from orderflow.research.edge_scout import select_fold
    summaries={'best':{'sharpe':2,'trades':40},'fallback':{'sharpe':1,'trades':40}}
    assert select_fold(summaries,{'fallback'})==('best',False)
    assert select_fold(summaries,{'fallback','best'})==('best',True)


def test_hourly_grid_does_not_treat_off_grid_special_candles_as_regular_hours(tmp_path):
    pd.DataFrame([{'symbol':'A','instrument_key':'NSE_EQ|A','sector_index':'NIFTY_50','nifty50':True}]).to_csv(tmp_path/'universe.csv',index=False)
    rows=[]
    for clock in ('09:15','10:15','11:45'):
        for symbol in ('A','NIFTY_50'):
            rows.append(dict(symbol=symbol,ts=pd.Timestamp('2025-01-02 '+clock,tz='Asia/Kolkata'),session_date=date(2025,1,2),open=10,high=10,low=10,close=10,volume=10))
    pd.DataFrame(rows).to_parquet(tmp_path/'candles_hourly.parquet',index=False)
    result=load_panel(tmp_path,'hourly')
    assert len(result.times)==2
    assert set(result.times.tz_convert('Asia/Kolkata').minute)=={15}


def test_final_report_rejects_an_unfinished_daily_only_screen(tmp_path):
    import json
    from orderflow.research.edge_report import build_report
    source=tmp_path/'results.json'
    source.write_text(json.dumps({'variants':[{'status':'DEFERRED_HOURLY_DOWNLOAD'}]}))
    with pytest.raises(ValueError,match='unfinished'):
        build_report(source,destination=tmp_path/'report.md')
    assert not (tmp_path/'report.md').exists()
