"""T12 cached 50-symbol day benchmark; root runs serially with other features."""
import json
from time import perf_counter

import pyarrow.parquet as pq

from orderflow.layers.levels.core import levels

bars = pq.read_table('/tmp/orderflow-day-bars.parquet')
trades_metadata = pq.read_metadata('/tmp/orderflow-day-trades.parquet')
as_of = max(bars.column('available_at').to_pylist())
started = perf_counter()
result = levels(bars, as_of=as_of)
elapsed = perf_counter()-started
print(json.dumps(dict(task='T12', input_bars=bars.num_rows,
    input_tick_equivalents=trades_metadata.num_rows, output_levels=result.num_rows,
    seconds=elapsed, bars_per_second=bars.num_rows/elapsed,
    tick_equivalents_per_second=trades_metadata.num_rows/elapsed,
    scope='levels from cached 50-stock plus 3-index six-hour simulated-day bars; upstream excluded')))
