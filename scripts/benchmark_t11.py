"""T11 feature-only cached simulated 50-symbol-day benchmark; no network.

Run after benchmark_t04.py has created /tmp/orderflow-day-bars.parquet.
SMA/strict/eq are explicit benchmark policies, not project defaults.
"""
import json
from decimal import Decimal
from time import perf_counter
import pyarrow.parquet as pq
from orderflow.layers.smc.core import smc

if __name__=='__main__':
    bars=pq.read_table('/tmp/orderflow-day-bars.parquet')
    cutoff=max(bars.column('available_at').to_pylist())
    start=perf_counter()
    levels,events=smc(bars,as_of=cutoff,tick_size=Decimal('.05'),atr_smoothing='sma',swing_tie_policy='strict',fvg_comparator='eq')
    seconds=perf_counter()-start
    ticks=1144800
    print(json.dumps(dict(task='T11',symbols=50,context_instruments=3,simulated_seconds=21600,input_bars=bars.num_rows,levels=levels.num_rows,events=events.num_rows,seconds=seconds,ticks_equivalent_per_second=round(ticks/seconds,2),scope='SMC over cached 1m bars, excludes simulator/decode/trades/bar generation',policies=dict(atr_smoothing='sma',swing_tie_policy='strict',fvg_comparator='eq')),indent=2))
