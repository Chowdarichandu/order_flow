"""T03 queue/writer ownership, shutdown, drop accounting and reconnect checks."""
from datetime import datetime, timezone
import asyncio
import threading

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from orderflow.ingest.recorder import Recorder, FeedClient, FeedLock
from orderflow.sim.feed import FeedSimulator, SimulatedDisconnect
from orderflow.decode.feed import Decoder
from orderflow.schema import RAW_MESSAGE_SCHEMA

START = datetime(2026, 10, 1, 3, 45, tzinfo=timezone.utc)


def read_parts(root):
    return [pq.read_table(path) for path in sorted(root.glob('raw/**/*.parquet'))]


def test_receive_only_enqueues_and_writer_is_separate(tmp_path, monkeypatch):
    writer_threads = []
    original = pq.write_table
    def record_thread(*args, **kwargs):
        writer_threads.append(threading.get_ident())
        return original(*args, **kwargs)
    monkeypatch.setattr(pq, 'write_table', record_thread)
    recorder = Recorder(tmp_path, capacity=100, batch_size=5, flush_seconds=.01)
    receiver_thread = threading.get_ident()
    with recorder:
        for frame in FeedSimulator(start=START).frames(20):
            assert recorder.receive(frame)
    assert recorder.metrics['received'] == 20 and recorder.metrics['written'] == 20
    assert recorder.metrics['dropped'] == 0
    assert writer_threads and all(i != receiver_thread for i in writer_threads)
    table = pa.concat_tables(read_parts(tmp_path))
    assert table.schema.equals(RAW_MESSAGE_SCHEMA)
    assert table.num_rows == 20
    assert not list(tmp_path.rglob('*.tmp'))


def test_bounded_drop_accounting_without_waiting(tmp_path):
    recorder = Recorder(tmp_path, capacity=1, batch_size=1)
    frames = list(FeedSimulator(start=START).frames(2))
    assert recorder.receive(frames[0])
    assert not recorder.receive(frames[1])
    assert recorder.metrics['received'] == 2
    assert recorder.metrics['dropped'] == 1
    recorder.start()
    recorder.close()
    assert recorder.metrics['written'] == 1


def test_writer_failure_is_visible_and_close_cannot_hang(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('disk full')
    monkeypatch.setattr(pq, 'write_table', fail)
    recorder = Recorder(tmp_path, capacity=10, batch_size=1)
    recorder.start()
    recorder.receive(next(FeedSimulator(start=START).frames(1)))
    with pytest.raises(RuntimeError, match='writer'):
        recorder.close()
    assert recorder.metrics['written'] == 0


def test_only_one_feed_owner(tmp_path):
    with FeedLock(tmp_path/'feed.lock'):
        with pytest.raises(RuntimeError, match='owns'):
            with FeedLock(tmp_path/'feed.lock'):
                pass
    with FeedLock(tmp_path/'feed.lock'):
        pass


def test_quality_report_counts_decoder_anomalies(tmp_path):
    sim = FeedSimulator(start=START, scenario='duplicate')
    decoder = Decoder(sim.instruments)
    with Recorder(tmp_path, batch_size=4) as recorder:
        for frame in sim.frames(8):
            decoder.decode(frame)
            recorder.receive(frame)
    report = recorder.quality(decoder.counters)
    assert report['duplicates'] == 4
    assert report['dropped'] == 0 and report['written'] == 8


def test_six_hour_session_zero_drops_and_lossless_replay(tmp_path):
    sim = FeedSimulator(start=START)
    recorder = Recorder(tmp_path, capacity=25000, batch_size=1000)
    expected_first = None
    expected_last = None
    with recorder:
        for frame in sim.frames(6*60*60):
            if expected_first is None:
                expected_first = frame['payload']
            expected_last = frame['payload']
            assert recorder.receive(frame)
    table = pa.concat_tables(read_parts(tmp_path)).sort_by('sequence')
    assert table.num_rows == 21600
    assert table['payload'][0].as_py() == expected_first
    assert table['payload'][-1].as_py() == expected_last
    assert recorder.metrics['dropped'] == 0
    assert recorder.metrics['written'] == 21600


def test_reconnect_reauthorizes_and_preserves_subscription(tmp_path):
    class API:
        calls = 0
        def authorize(self):
            self.calls += 1
            return 'simulator://feed'
    class Socket:
        def __init__(self, broken=False):
            self.sent = []
            self.broken = broken
        async def send(self, payload):
            self.sent.append(payload)
        def __aiter__(self):
            return self
        async def __anext__(self):
            if self.broken:
                self.broken = False
                raise SimulatedDisconnect()
            raise StopAsyncIteration
        async def close(self):
            pass
    sockets = []
    async def connect(url):
        socket = Socket(broken=not sockets)
        sockets.append(socket)
        return socket
    api = API()
    recorder = Recorder(tmp_path)
    client = FeedClient(api, connect, recorder, instruments=['NSE_EQ|TEST'], retry_seconds=0)
    with recorder:
        asyncio.run(client.run(max_connections=2))
    assert api.calls == 2
    assert recorder.metrics['disconnects'] == 1
    assert all(socket.sent for socket in sockets)


def test_corrupt_frame_is_recorded_and_quality_failure_counted(tmp_path):
    sim = FeedSimulator(start=START)
    frame = next(sim.frames(1))
    frame['payload'] = b'\xff'
    with Recorder(tmp_path, batch_size=1, decoder=Decoder(sim.instruments)) as recorder:
        recorder.receive(frame)
    assert recorder.quality()['decode_failures'] == 1
    table = pa.concat_tables(read_parts(tmp_path))
    assert table['payload'][0].as_py() == b'\xff'
    assert 'DECODE_ERROR' in table['flags'][0].as_py()
