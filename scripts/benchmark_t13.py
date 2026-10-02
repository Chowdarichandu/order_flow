"""T13 final context snapshot over cached 50-stock six-hour simulator bars.

Measured context only: no simulator, decoder, bar building, or VWAP preparation.
No prior-year VIX / 20-session liquidity history exists in this single-day cache;
those dimensions correctly remain null with quality flags (covered separately
by known-answer tests). No full-day tick expansion is needed.
"""
from datetime import time
import json
from time import perf_counter
import pyarrow as pa
import pyarrow.parquet as pq
from orderflow.schema import FEATURE_SCHEMA,TICK_SCHEMA,LEVEL_SCHEMA,EVENT_SCHEMA
from orderflow.layers.context.core import context_snapshot


def main()->None:
    bars=pq.read_table('/tmp/orderflow-day-bars.parquet')
    raw=bars.to_pylist();at=max(r['available_at'] for r in raw)
    instruments=sorted({r['symbol'] for r in raw})
    # The simulator's 50 cash keys use NSE_EQ; index records are excluded.
    universe=tuple(sorted({r['symbol'] for r in raw if r['instrument_key'].startswith('NSE_EQ|')}))
    remaining=tuple(s for s in instruments if s not in universe)
    index_symbols=(remaining+('MISSING_INDEX_1','MISSING_INDEX_2'))[:2]
    vwap_rows=[]
    for s in instruments:
        rows=[r for r in raw if r['symbol']==s];volume=sum(r['volume'] for r in rows)
        value=sum(float((r['high']+r['low']+r['close'])/3)*r['volume'] for r in rows)/volume if volume else None
        r=rows[-1]
        vwap_rows.append(dict(symbol=s,instrument_key=r['instrument_key'],session_date=r['session_date'],minute=at,name='SESSION_VWAP',level=None,value=value,r_squared=None,n=None,unknown_share=None,window_start=None,window_end=None,source='BENCHMARK_BAR_VWAP',method='APPROXIMATE',confidence='LOW',flags=[],available_at=at,inputs=[]))
    features=pa.Table.from_pylist(vwap_rows,schema=FEATURE_SCHEMA)
    begin=perf_counter()
    result=context_snapshot(bars,features,pa.Table.from_pylist([],schema=TICK_SCHEMA),pa.Table.from_pylist([],schema=LEVEL_SCHEMA),pa.Table.from_pylist([],schema=EVENT_SCHEMA),as_of=at,sector_map={},index_symbols=index_symbols,vix_symbol='INDIA_VIX',vix_percentile_method='weak',vix_thresholds=(25,75),time_boundaries={'MORNING':(time(9,45),time(11)),'MIDDAY':(time(11),time(13)),'AFTERNOON':(time(13),time(14,45))},value_thresholds=(100,1000),spread_thresholds=(.01,.05),index_policy='unanimous',advancer_basis='session_open',universe=universe)
    elapsed=perf_counter()-begin
    ticks=pq.read_metadata('/tmp/orderflow-day-trades.parquet').num_rows
    print(json.dumps(dict(task='T13',stock_symbols=len(universe),simulated_hours=6,input_bars=bars.num_rows,tick_equivalents=ticks,output_rows=result.num_rows,elapsed_seconds=elapsed,bars_per_second=bars.num_rows/elapsed,tick_equivalents_per_second=ticks/elapsed,mode='final context snapshot; cached bars; absent optional historical contexts are null and flagged'),indent=2))


if __name__=='__main__':main()
