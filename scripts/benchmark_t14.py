"""T14 minute-by-minute zone benchmark over cached official simulated-day bars.

Crafted active component/ATR fixtures isolate the zone stage. This is not a
benchmark of the SMC/profile/VWAP upstream stages or a strategy evaluation.
"""
from decimal import Decimal as D
import json
from time import perf_counter
import pyarrow as pa
import pyarrow.parquet as pq
from orderflow.schema import LEVEL_SCHEMA,FEATURE_SCHEMA,BAR_SCHEMA
from orderflow.zones.core import ZonePolicy,zone_snapshot


def main() -> None:
    """Measure 360 point-in-time evaluations for 50 stocks and 3 indices."""
    bars=pq.read_table('/tmp/orderflow-day-bars.parquet')
    bar_rows=bars.to_pylist()
    # Isolate the zone stage with compact upstream provenance. Market values,
    # timestamps and quality flags are unchanged. Zone outputs still cite every
    # direct bar, level and ATR input; expanding upstream raw tick leaves is excluded.
    for row in bar_rows:
        row["inputs"]=[]
    bars=pa.Table.from_pylist(bar_rows,schema=BAR_SCHEMA)
    first={}
    for row in bar_rows:
        first.setdefault((row['instrument_key'],row['session_date']),row)
    level_rows=[];atr_rows=[]
    for key,row in first.items():
        created=row['available_at']
        base=dict(symbol=row['symbol'],instrument_key=key[0],session_date=key[1],
                  source='SIMULATED_ZONE_FIXTURE',method='ESTIMATE',confidence='LOW',
                  flags=[],available_at=created,inputs=[])
        for i,kind in enumerate(('POC','VWAP','OB','FVG')):
            price=row['open']+D('.25')*i
            level_rows.append(dict(base,record_id=f'{key[0]}:fixture:{kind}',type=kind,
                timeframe_minutes=None,low=price,high=price,side='SUPPORT',origin_at=created,
                created_at=created,invalidated_at=None,mitigated_at=None,state='ACTIVE'))
        atr_rows.append(dict(base,minute=created,name='ATR_14_5M',level=5,value=4,
            r_squared=None,n=14,unknown_share=None,window_start=None,window_end=created))
    levels=pa.Table.from_pylist(level_rows,schema=LEVEL_SCHEMA)
    atr=pa.Table.from_pylist(atr_rows,schema=FEATURE_SCHEMA)
    policy=ZonePolicy(linkage='single_linkage',touch_policy='entry_episode',
                      invalidation_policy='close_beyond_edge',
                      side_policy='source_side_else_creation_close',
                      freshness_policy='cluster_formation')
    minutes=sorted({row['bar_end'] for row in bar_rows})
    begin=perf_counter();output_rows=0
    for minute in minutes:
        output_rows+=zone_snapshot(levels,bars,atr,as_of=minute,policy=policy).num_rows
    elapsed=perf_counter()-begin
    ticks=pq.ParquetFile('/tmp/orderflow-day-trades.parquet').metadata.num_rows
    print(json.dumps(dict(task='T14',stock_symbols=50,context_instruments=3,
        simulated_hours=6,ticks_equivalent=ticks,input_bars=bars.num_rows,
        minute_evaluations=len(minutes),output_rows=output_rows,elapsed_seconds=elapsed,
        ticks_equivalent_per_second=ticks/elapsed,
        scope='zone snapshot each minute; cached simulated bars and crafted active level/ATR fixtures; compact upstream bar provenance; excludes upstream layers and leaf expansion',
        policies=dict(linkage=policy.linkage,touch_policy=policy.touch_policy,
                      invalidation_policy=policy.invalidation_policy,
                      freshness_policy=policy.freshness_policy)),indent=2))


if __name__=='__main__':main()
