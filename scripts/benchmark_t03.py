"""Six-hour/50-stock raw recorder benchmark in a temporary workspace."""
from datetime import datetime, timezone
from pathlib import Path
import json
import tempfile
from time import perf_counter
from orderflow.sim.feed import FeedSimulator
from orderflow.ingest.recorder import Recorder


def main() -> None:
    """Report generated raw frames persisted off the receive thread, including drops."""
    sim = FeedSimulator(start=datetime(2026,10,1,3,45,tzinfo=timezone.utc), symbols=50)
    with tempfile.TemporaryDirectory() as folder:
        recorder = Recorder(Path(folder), capacity=25000, batch_size=1000)
        begin = perf_counter()
        with recorder:
            for frame in sim.frames(21600):
                recorder.receive(frame)
        elapsed = perf_counter()-begin
        result = dict(task='T03', stock_symbols=50, context_instruments=3,
                      simulated_hours=6, elapsed_seconds=elapsed,
                      ticks_per_second=21600*53/elapsed, metrics=recorder.quality(),
                      mode='official V3 generation + raw Parquet writer')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
