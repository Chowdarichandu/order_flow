"""Memory-bounded T08 benchmark using the cached simulated 50-symbol day.

Run: PYTHONPATH=src python scripts/benchmark_t08.py
Excludes simulation/decode; includes construction of required T06 footprints.
V=10,000 is a predeclared synthetic trailing-volume fixture, not today's volume.
Dominance=.6 and simple returns are explicit benchmark choices, not defaults.
"""
from datetime import datetime,timedelta,timezone
from decimal import Decimal
import json
from time import perf_counter

import pyarrow.compute as pc
import pyarrow.parquet as pq

from orderflow.layers.orderflow.footprint import footprint
from orderflow.layers.orderflow.flow import vpin,kyle_lambda,flow_events


def main() -> None:
    """Evaluate all three producers, one instrument at a time to bound memory."""
    trades=pq.read_table('/tmp/orderflow-day-trades.parquet')
    bars=pq.read_table('/tmp/orderflow-day-bars.parquet')
    end=datetime(2026,10,1,3,45,tzinfo=timezone.utc)+timedelta(hours=6)
    keys=pc.unique(trades['instrument_key']).to_pylist();counts=dict(vpin=0,kyle=0,events=0)
    started=perf_counter()
    for key in keys:
        day_trades=trades.filter(pc.equal(trades['instrument_key'],key))
        day_bars=bars.filter(pc.equal(bars['instrument_key'],key))
        table=vpin(day_trades,bucket_size=10000,as_of=end)
        counts['vpin']+=table.num_rows;del table
        table=kyle_lambda(day_bars,as_of=end,return_definition='simple')
        counts['kyle']+=table.num_rows;del table
        levels=footprint(day_trades,day_bars,tick_size=Decimal('.05'))
        table=flow_events(day_bars,levels,tick_size=Decimal('.05'),dominant_fraction=.6,as_of=end)
        counts['events']+=table.num_rows;del table,levels,day_trades,day_bars
    elapsed=perf_counter()-started
    print(json.dumps(dict(task='T08',stock_symbols=50,context_instruments=3,simulated_hours=6,ticks=trades.num_rows,
        output_rows=counts,elapsed_seconds=elapsed,ticks_per_second=trades.num_rows/elapsed,
        mode='cached simulation; T06 footprint dependency plus T08 VPIN/impact/events; sequential instruments',
        benchmark_parameters=dict(bucket_size=10000,dominant_fraction=.6,return_definition='simple')),indent=2))


if __name__=='__main__':main()
