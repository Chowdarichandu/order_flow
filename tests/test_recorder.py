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


def test_soft_status_failure_does_not_stop_recording(tmp_path):
    def bad_status(metrics):
        raise OSError('status disk problem')
    with Recorder(tmp_path, batch_size=1, on_flush=bad_status) as recorder:
        for frame in FeedSimulator(start=START).frames(3):
            recorder.receive(frame)
    assert recorder.metrics['written'] == 3 and recorder.error is None


@pytest.mark.parametrize('legacy',[False,True])
def test_websocket_handshake_status_and_sanitized_body_are_logged(tmp_path,caplog,legacy):
    from datetime import timedelta
    from types import SimpleNamespace
    from orderflow.auth.core import TokenFile
    token='SYNTHETIC_PRIVATE_TOKEN'
    token_file=TokenFile(tmp_path/'token.json')
    # Even an expired credential still needs redaction from a failure body.
    token_file.write(token,START-timedelta(days=1))
    class API:
        def __init__(self):self.token_file=token_file
        def authorize(self):return 'wss://simulator.invalid/feed?token=URL_SECRET'
    class HandshakeFailure(Exception):
        def __init__(self):
            super().__init__('wss://simulator.invalid/feed?token=URL_SECRET')
            body=(f'Cloudflare Error 1010 echoed {token}; '
                  'access_token=BODY_PRIVATE secret="BODY_SECRET"').encode()
            if legacy:
                self.status_code=403;self.body=body
            else:self.response=SimpleNamespace(status_code=403,body=body)
    async def connect(url):raise HandshakeFailure()
    recorder=Recorder(tmp_path/'recordings')
    client=FeedClient(API(),connect,recorder,instruments=['NSE_EQ|TEST'],retry_seconds=0)
    with recorder:asyncio.run(client.run(max_connections=1))
    text=caplog.text
    assert 'status=403' in text and 'Cloudflare Error 1010' in text
    assert '[REDACTED]' in text
    assert all(secret not in text for secret in (token,'BODY_PRIVATE','BODY_SECRET','URL_SECRET'))
    assert 'wss://' not in text
    assert recorder.metrics['disconnects']==1


def test_websocket_json_failure_redacts_unknown_token_fields(tmp_path,caplog):
    from types import SimpleNamespace
    class API:
        def authorize(self):return 'simulator://feed'
    class Failure(Exception):
        def __init__(self):
            self.response=SimpleNamespace(status_code=401,
                body=b'{"message":"expired credentials","refresh_token":"UNKNOWN_SECRET"}')
    async def connect(url):raise Failure()
    recorder=Recorder(tmp_path)
    client=FeedClient(API(),connect,recorder,instruments=['NSE_EQ|TEST'],retry_seconds=0)
    with recorder:asyncio.run(client.run(max_connections=1))
    assert 'status=401' in caplog.text and 'expired credentials' in caplog.text
    assert 'UNKNOWN_SECRET' not in caplog.text and '[REDACTED]' in caplog.text


def test_writer_measures_exact_exchange_lag_and_clock_skew_off_receive(tmp_path):
    from datetime import timedelta
    from zoneinfo import ZoneInfo
    sim=FeedSimulator(start=START)
    frames=list(sim.frames(3))
    # Represent the receipt in IST to verify comparison uses absolute aware time.
    frames[0]['receipt_ts']=(START+timedelta(milliseconds=1500)).astimezone(ZoneInfo('Asia/Kolkata'))
    frames[1]['receipt_ts']=START+timedelta(seconds=1,milliseconds=25)
    frames[2]['receipt_ts']=START+timedelta(seconds=2,milliseconds=-200)
    decoder=Decoder(sim.instruments)
    receiver=threading.get_ident();decoder_threads=[]
    original=decoder.decode
    def decode(frame):
        decoder_threads.append(threading.get_ident());return original(frame)
    decoder.decode=decode
    recorder=Recorder(tmp_path,capacity=10,batch_size=3,decoder=decoder)
    for frame in frames:assert recorder.receive(frame)
    assert decoder_threads==[]
    recorder.close()
    report=recorder.quality()
    assert report['max_exchange_lag_ms']==1500
    assert report['negative_exchange_lag_count']==4
    assert report['max_clock_skew_ms']==200
    assert report['max_queue_lag_ms']>=0
    assert decoder_threads and all(i!=receiver for i in decoder_threads)
    assert decoder.counters['FIRST_TICK']==4
    assert report['written']==3 and report['decode_failures']==0


def test_exchange_lag_metrics_do_not_recount_or_hide_decoder_flags(tmp_path):
    sim=FeedSimulator(start=START,scenario='duplicate')
    decoder=Decoder(sim.instruments)
    with Recorder(tmp_path,batch_size=2,decoder=decoder) as recorder:
        for frame in sim.frames(8):recorder.receive(frame)
    report=recorder.quality()
    assert report['duplicates']==4 and report['gaps']==0
    assert report['negative_exchange_lag_count']==0
    assert report['max_exchange_lag_ms']==1050


def test_missing_exchange_time_is_counted_without_fabricated_lag(tmp_path):
    from upstox_client.feeder.proto import MarketDataFeedV3_pb2 as pb
    sim=FeedSimulator(start=START)
    frame=next(sim.frames(1))
    message=pb.FeedResponse.FromString(frame['payload'])
    message.currentTs=0
    frame['payload']=message.SerializeToString(deterministic=True)
    with Recorder(tmp_path,batch_size=1,decoder=Decoder(sim.instruments)) as recorder:
        recorder.receive(frame)
    report=recorder.quality()
    assert report['missing_exchange_timestamps']==4
    assert report['max_exchange_lag_ms']==0 and report['max_clock_skew_ms']==0
    assert report['negative_exchange_lag_count']==0 and report['decode_failures']==0
