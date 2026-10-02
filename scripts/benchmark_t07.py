"""Memory-bounded depth benchmark: official 50-stock/six-hour V3 simulation."""
from datetime import datetime,timezone
import json
from pathlib import Path
from time import perf_counter
import pyarrow as pa
import pyarrow.parquet as pq
from orderflow.decode.feed import Decoder
from orderflow.layers.orderflow.depth import depth_feature_batches
from orderflow.sim.feed import FeedSimulator


def main() -> None:
    """Time causal depth production; explicitly exclude simulator/wire decode time."""
    cache=Path('/tmp/orderflow-day-ticks.parquet')
    ticks_count=0
    feed_seconds=0.0
    start=datetime(2026,10,1,3,45,tzinfo=timezone.utc)

    def batches():
        nonlocal ticks_count,feed_seconds
        if cache.exists():
            reader=iter(pq.ParquetFile(cache).iter_batches(batch_size=500))
            while True:
                begin=perf_counter()
                try:batch=next(reader)
                except StopIteration:return
                table=pa.Table.from_batches([batch])
                feed_seconds+=perf_counter()-begin
                ticks_count+=table.num_rows
                yield table
        else:
            simulator=FeedSimulator(start=start,symbols=50)
            decoder=Decoder(simulator.instruments)
            frames=iter(simulator.frames(21600))
            while True:
                begin=perf_counter()
                tables=[]
                for _ in range(10):
                    try:frame=next(frames)
                    except StopIteration:break
                    tables.append(decoder.decode(frame))
                if not tables:return
                table=pa.concat_tables(tables)
                feed_seconds+=perf_counter()-begin
                ticks_count+=table.num_rows
                yield table

    begin=perf_counter()
    output_rows=0
    for table in depth_feature_batches(batches(),levels=5,trailing_window=60,
                                      iceberg_window=60,output_batch_size=1000):
        output_rows+=table.num_rows
    elapsed=perf_counter()-begin-feed_seconds
    print(json.dumps(dict(task='T07',stock_symbols=50,context_instruments=3,
                          simulated_hours=6,ticks=ticks_count,
                          output_rows=output_rows,elapsed_seconds=elapsed,
                          ticks_per_second=ticks_count/elapsed,
                          simulator_decode_seconds=feed_seconds,
                          mode='streaming depth features; simulation/decode/cache read excluded'),indent=2))


if __name__=='__main__':main()
