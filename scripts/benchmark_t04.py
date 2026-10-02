"""50-stock six-hour estimated trade/bar benchmark using official V3 decoding."""
from datetime import datetime,timedelta,timezone
import json
from time import perf_counter
import pyarrow as pa
import pyarrow.parquet as pq
from orderflow.sim.feed import FeedSimulator
from orderflow.decode.feed import Decoder
from orderflow.trades.core import classify_ticks
from orderflow.bars.core import time_bars


def main() -> None:
    """Measure classification+bar cost separately from simulated wire decoding."""
    start=datetime(2026,10,1,3,45,tzinfo=timezone.utc)
    sim=FeedSimulator(start=start,symbols=50);decoder=Decoder(sim.instruments)
    tables=[decoder.decode(frame) for frame in sim.frames(21600)]
    ticks=pa.concat_tables(tables);del tables
    begin=perf_counter();trades=classify_ticks(ticks)
    bars=time_bars(trades,minutes=1,as_of=start+timedelta(hours=6))
    elapsed=perf_counter()-begin
    pq.write_table(trades,'/tmp/orderflow-day-trades.parquet')
    pq.write_table(bars,'/tmp/orderflow-day-bars.parquet')
    print(json.dumps(dict(task='T04',symbols=50,context_instruments=3,simulated_hours=6,
                         ticks=ticks.num_rows,bars=bars.num_rows,elapsed_seconds=elapsed,
                         ticks_per_second=ticks.num_rows/elapsed,mode='classification + 1m bars; decoding excluded'),indent=2))


if __name__=='__main__':main()
