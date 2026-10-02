"""T05 resumable history, throttle/retry, manifests and raw importer tests."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from orderflow.ingest.history import HistoryDownloader, import_recordings, cross_check
from orderflow.sim.history import candle_response
from orderflow.sim.feed import FeedSimulator
from orderflow.ingest.recorder import Recorder
from orderflow.decode.feed import Decoder
from orderflow.schema import CANDLE_SCHEMA

START = datetime(2026, 10, 1, 3, 45, tzinfo=timezone.utc)


class Api:
    def __init__(self, response):
        self.response, self.calls = response, []
    def request(self, method, path):
        self.calls.append((method, path))
        return type('Reply', (), {'json': lambda obj: self.response})()


def test_history_round_trip_resume_and_encoded_key(tmp_path):
    api = Api(candle_response(START, 3))
    download = HistoryDownloader(api, tmp_path, now=lambda: START+timedelta(hours=6), sleep=lambda _:None)
    result = download.day('TEST', 'NSE_EQ|TEST', START.date())
    assert result == 'DONE'
    file = next(tmp_path.glob('history/**/*.parquet'))
    table = pq.ParquetFile(file).read()
    assert table.schema.equals(CANDLE_SCHEMA) and table.num_rows == 3
    assert '%7C' in api.calls[0][1]
    assert download.day('TEST', 'NSE_EQ|TEST', START.date()) == 'CACHED'
    assert len(api.calls) == 1


def test_manifest_records_gaps_and_bhavcopy_difference(tmp_path):
    api = Api(candle_response(START, 5, scenario='gap_duplicate_out_of_order'))
    downloader = HistoryDownloader(api,tmp_path,now=lambda: START+timedelta(hours=6),sleep=lambda _:None)
    downloader.day('TEST','NSE_EQ|TEST',START.date())
    manifest = json.loads((tmp_path/'history/manifest.json').read_text())
    assert manifest['NSE_EQ|TEST:2026-10-01']['quality_flags'] == ['DUPLICATE', 'GAP', 'OUT_OF_ORDER']
    table = pq.ParquetFile(next(tmp_path.glob('history/**/*.parquet'))).read()
    check = cross_check(table, {'volume': 0, 'high': 101, 'low': 90, 'close': 100})
    assert check['volume_difference'] > 0 and not check['matches']


def test_missing_history_is_a_gap_not_silent_success(tmp_path):
    api = Api({'status':'success','data':{'candles':[]}})
    downloader = HistoryDownloader(api,tmp_path,now=lambda: START+timedelta(hours=6),sleep=lambda _:None)
    assert downloader.day('TEST','NSE_EQ|TEST',START.date()) == 'GAP'
    assert json.loads((tmp_path/'history/manifest.json').read_text())['NSE_EQ|TEST:2026-10-01']['state'] == 'GAP'


def test_throttle_retry_and_holiday_skip(tmp_path):
    class RetryApi(Api):
        def request(self, method, path):
            if not self.calls:
                self.calls.append((method,path))
                raise RuntimeError('temporary')
            return super().request(method,path)
    delays=[]
    api=RetryApi(candle_response(START,1))
    download=HistoryDownloader(api,tmp_path,now=lambda:START+timedelta(hours=6),sleep=delays.append, throttle_seconds=2)
    assert download.day('TEST','NSE_EQ|TEST',START.date()) == 'DONE'
    assert delays == [2,2]
    assert download.day('TEST','NSE_EQ|TEST',START.date(), is_trading_day=lambda day:False) == 'HOLIDAY'


def test_importer_round_trip_and_idempotence(tmp_path):
    source=tmp_path/'old'
    sim=FeedSimulator(start=START)
    with Recorder(source,batch_size=3) as recorder:
        for frame in sim.frames(5):
            recorder.receive(frame)
    target=tmp_path/'new'
    stats=import_recordings(source,target,Decoder(sim.instruments))
    assert stats['frames'] == 5 and stats['ticks'] == 20
    assert len(list(target.glob('raw/**/*.parquet'))) > 0
    table=pq.ParquetFile(next(target.glob('ticks/**/*.parquet'))).read()
    assert table.num_rows > 0
    second=import_recordings(source,target,Decoder(sim.instruments))
    assert second['frames'] == 0 and second['skipped'] > 0


def test_importer_rejects_unknown_schema_without_mutating_source(tmp_path):
    import pyarrow as pa
    source=tmp_path/'old';source.mkdir()
    path=source/'unknown.parquet'
    pq.write_table(pa.table({'unknown':[1]}),path)
    before=path.read_bytes()
    with pytest.raises(ValueError,match='schema'):
        import_recordings(source,tmp_path/'new',Decoder({}))
    assert path.read_bytes() == before
