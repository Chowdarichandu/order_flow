"""Feature benchmarks on the cached official 50-stock/six-hour T04 simulation."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from time import perf_counter
import pyarrow.parquet as pq
from orderflow.layers.orderflow.footprint import footprint


def main() -> None:
    """Measure the chosen feature over all cached rows, excluding simulation/decode."""
    task=sys.argv[1]
    trades=pq.read_table('/tmp/orderflow-day-trades.parquet')
    bars=pq.read_table('/tmp/orderflow-day-bars.parquet')
    start=datetime(2026,10,1,3,45,tzinfo=timezone.utc);end=start+timedelta(hours=6)
    begin=perf_counter()
    if task=='T06':result=footprint(trades,bars,tick_size=Decimal('.05'))
    elif task=='T09':
        from orderflow.layers.profile.core import session_profile
        result=session_profile(trades,tick_size=Decimal('.05'),as_of=end)
    elif task=='T10':
        from orderflow.layers.vwap.core import vwap_features
        result=vwap_features(trades,as_of=end)
    else:raise ValueError('unsupported benchmark task')
    elapsed=perf_counter()-begin
    print(json.dumps(dict(task=task,stock_symbols=50,context_instruments=3,simulated_hours=6,
        ticks=trades.num_rows,output_rows=result.num_rows,elapsed_seconds=elapsed,
        ticks_per_second=trades.num_rows/elapsed,mode='feature only; cached official simulation'),indent=2))


if __name__=='__main__':main()
