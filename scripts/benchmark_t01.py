"""Benchmark a deterministic six-hour day; never contacts a live data source."""
from datetime import datetime, timezone
import json
from time import perf_counter

from orderflow.sim.feed import FeedSimulator
from orderflow.decode.feed import Decoder


def main() -> None:
    """Report V3 generation+Arrow decoding throughput for 50 stocks plus indices."""
    sim = FeedSimulator(start=datetime(2026, 10, 1, 3, 45, tzinfo=timezone.utc), symbols=50)
    decoder = Decoder(sim.instruments)
    started = perf_counter()
    ticks = 0
    for frame in sim.frames(6 * 60 * 60):
        ticks += decoder.decode(frame).num_rows
    elapsed = perf_counter() - started
    print(json.dumps(dict(task='T01', stock_symbols=50, context_instruments=3,
                         simulated_hours=6, snapshots=21600, ticks=ticks,
                         elapsed_seconds=elapsed, ticks_per_second=ticks / elapsed,
                         mode='official V3 generation + Arrow decode',
                         depth=5), indent=2))


if __name__ == '__main__':
    main()
