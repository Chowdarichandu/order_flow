"""Offline known-answer tests for public research downloads."""
from datetime import date, datetime, timezone
import json
from pathlib import Path
import pytest
from orderflow.research.edge_data import PublicCache, period_windows, normalize_candles, map_universe

class Response:
    status_code = 200
    content = b'{"status":"success","data":{"candles":[]}}'
    headers = {}

class Session:
    def __init__(self): self.calls = []
    def get(self, url, *, headers, timeout):
        self.calls.append((url, headers)); return Response()

def test_http_user_agent_and_resumable_cache(tmp_path):
    session = Session(); cache = PublicCache(tmp_path, session=session, rate=5)
    assert cache.get('https://api.upstox.com/example') == Response.content
    assert cache.get('https://api.upstox.com/example') == Response.content
    assert len(session.calls) == 1
    assert session.calls[0][1]['User-Agent'].startswith('orderflow-zero')
    assert 'Authorization' not in session.calls[0][1]
    manifest = json.loads((tmp_path / 'manifest.json').read_text())
    assert len(manifest) == 1
    entry = next(iter(manifest.values()))
    assert entry['sha256'] and entry['fetched_at'].endswith('+00:00')

def test_windows_cover_every_day_without_overlap():
    windows = period_windows(date(2022,1,1), date(2022,7,15), months=3)
    assert windows == [(date(2022,1,1),date(2022,3,31)),(date(2022,4,1),date(2022,6,30)),(date(2022,7,1),date(2022,7,15))]

def test_daily_availability_is_close_not_midnight_and_duplicates_counted():
    candle = ['2022-01-03T00:00:00+05:30',100,110,90,105,500,0]
    table, quality = normalize_candles([candle,candle],symbol='A',instrument_key='NSE_EQ|X',timeframe='daily',source_sha256='abc')
    assert table.num_rows == 1 and quality['duplicates'] == 1
    row = table.to_pylist()[0]
    assert row['available_at'] == datetime(2022,1,3,10,0,tzinfo=timezone.utc)
    assert row['session_date'] == date(2022,1,3)

def test_hourly_partial_final_bar_closes_at_market_close():
    candle=['2022-01-03T15:15:00+05:30',100,110,90,105,500,0]
    table,_=normalize_candles([candle],symbol='A',instrument_key='K',timeframe='hourly',source_sha256='s')
    assert table.to_pylist()[0]['available_at']==datetime(2022,1,3,10,0,tzinfo=timezone.utc)

def test_mapping_uses_isin_and_reports_missing():
    rows=[{'Symbol':'A','ISIN Code':'XYZ','Industry':'Information Technology'}, {'Symbol':'MISSING','ISIN Code':'NONE','Industry':'Power'}]
    instruments=[{'segment':'NSE_EQ','isin':'XYZ','instrument_key':'NSE_EQ|XYZ','trading_symbol':'RENAMED'}]
    mapped,missing=map_universe(rows,instruments)
    assert mapped[0]['instrument_key']=='NSE_EQ|XYZ'
    assert mapped[0]['sector_index']=='NIFTY_IT'
    assert missing[0]['symbol']=='MISSING'

def test_corrupt_cache_is_refetched(tmp_path):
    session=Session();cache=PublicCache(tmp_path,session=session)
    cache.get('https://example.com/a'); entry=next(iter(cache.manifest.values()))
    (tmp_path / entry['path']).write_bytes(b'broken')
    assert cache.get('https://example.com/a')==Response.content
    assert len(session.calls)==2

def test_retry_is_bounded_to_two_attempts_and_retains_user_agent(tmp_path, monkeypatch):
    monkeypatch.setattr('orderflow.research.edge_data.time.sleep', lambda _: None)
    class Failing(Session):
        def get(self,url,*,headers,timeout):
            self.calls.append((url,headers))
            r=Response();r.status_code=403;r.content=b'blocked';return r
    session=Failing();cache=PublicCache(tmp_path,session=session)
    with pytest.raises(RuntimeError,match='HTTP 403'):
        cache.get('https://api.upstox.com/public')
    assert len(session.calls)==2
    assert all(call[1]['User-Agent'] for call in session.calls)
    assert not cache.manifest

def test_invalid_ohlc_is_counted_not_used():
    table,quality=normalize_candles([['2022-01-03T00:00:00+05:30',100,80,90,105,500,0]],symbol='A',instrument_key='K',timeframe='daily',source_sha256='s')
    assert table.num_rows==0 and quality['invalid']==1

def test_special_evening_session_availability_cannot_precede_bar_start():
    candle=['2022-10-24T18:15:00+05:30',100,110,90,105,500,0]
    table,quality=normalize_candles([candle],symbol='A',instrument_key='K',timeframe='hourly',source_sha256='s')
    row=table.to_pylist()[0]
    assert row['available_at']>=row['ts']
    assert quality['outside_regular_session']==1

def test_intraperiod_gap_report_does_not_call_prelisting_missing():
    from orderflow.research.edge_data import missing_observations
    rows=[{'symbol':'A','session_date':date(2022,1,4),'ts':datetime(2022,1,4,tzinfo=timezone.utc)}, {'symbol':'A','session_date':date(2022,1,6),'ts':datetime(2022,1,6,tzinfo=timezone.utc)}]
    reference=[datetime(2022,1,d,tzinfo=timezone.utc) for d in (3,4,5,6)]
    gaps=missing_observations(rows,reference,timeframe='daily')
    assert len(gaps)==1 and gaps[0]['start']=='2022-01-05'
    assert gaps[0]['reason']=='ABSENT_ON_OBSERVED_NIFTY_50_SESSION'

def test_daily_raw_noon_timestamp_maps_to_session_midnight():
    candle=['2022-01-03T12:00:00+05:30',100,110,90,105,500,0]
    table,_=normalize_candles([candle],symbol='A',instrument_key='K',timeframe='daily',source_sha256='s')
    row=table.to_pylist()[0]
    assert row['ts']==datetime(2022,1,2,18,30,tzinfo=timezone.utc)
    assert row['source_ts']==datetime(2022,1,3,6,30,tzinfo=timezone.utc)

def test_conflicting_same_day_duplicates_are_flagged_not_silently_selected():
    a=['2022-01-03T00:00:00+05:30',100,110,90,105,500,0]
    b=['2022-01-03T12:00:00+05:30',101,111,91,106,500,0]
    table,q=normalize_candles([b,a],symbol='A',instrument_key='K',timeframe='daily',source_sha256='s')
    assert table.num_rows==1 and q['conflicting_duplicates']==1
    assert 'CONFLICTING_DUPLICATE_CANDLE' in table.to_pylist()[0]['quality_flags']

def test_future_candles_cannot_change_earlier_normalization():
    a=['2022-01-03T00:00:00+05:30',100,110,90,105,500,0]
    b=['2022-01-04T00:00:00+05:30',105,115,95,110,550,0]
    earlier,_=normalize_candles([a],symbol='A',instrument_key='K',timeframe='daily',source_sha256='same')
    complete,_=normalize_candles([b,a],symbol='A',instrument_key='K',timeframe='daily',source_sha256='same')
    assert complete.to_pylist()[0]==earlier.to_pylist()[0]

def test_default_public_session_never_reads_netrc_or_sends_authorization(tmp_path, monkeypatch):
    import requests
    def forbidden(*args,**kwargs):raise AssertionError('research must not read credentials')
    monkeypatch.setattr('requests.sessions.get_netrc_auth',forbidden)
    cache=PublicCache(tmp_path)
    prepared=cache.session.prepare_request(requests.Request('GET','https://api.upstox.com/public'))
    assert 'Authorization' not in prepared.headers
    cache.session.rebuild_auth(prepared,Response())
    assert 'Authorization' not in prepared.headers

def test_missing_entire_hourly_session_is_found_using_daily_index_sessions():
    from orderflow.research.edge_data import hourly_session_gaps
    rows=[{'symbol':'A','session_date':date(2022,1,3)}, {'symbol':'A','session_date':date(2022,1,5)}]
    missing=hourly_session_gaps(rows,[date(2022,1,3),date(2022,1,4),date(2022,1,5)])
    assert missing==[{'symbol':'A','timeframe':'hourly','start':'2022-01-04','end':'2022-01-04','reason':'ENTIRE_HOURLY_SESSION_ABSENT_ON_OBSERVED_NIFTY_50_DAILY_SESSION'}]

def test_daily_availability_waits_for_evening_index_session_close():
    from orderflow.research.edge_data import align_daily_availability
    day=['2022-10-24T00:00:00+05:30',100,110,90,105,500,0]
    hour=['2022-10-24T18:15:00+05:30',100,110,90,105,500,0]
    daily,_=normalize_candles([day],symbol='A',instrument_key='K',timeframe='daily',source_sha256='d')
    hourly,_=normalize_candles([hour],symbol='NIFTY_50',instrument_key='I',timeframe='hourly',source_sha256='h')
    adjusted,count=align_daily_availability(daily,hourly)
    assert count==1
    row=adjusted.to_pylist()[0]
    assert row['available_at']==datetime(2022,10,24,13,45,tzinfo=timezone.utc)
    assert 'SPECIAL_SESSION_CLOSE_FROM_HOURLY_INDEX' in row['quality_flags']

def test_coverage_boundaries_are_explicit_unknown_ranges_not_listing_claims():
    from orderflow.research.edge_data import coverage_boundaries
    rows=[{'symbol':'A','session_date':date(2022,1,4)},{'symbol':'A','session_date':date(2022,1,6)}]
    assert coverage_boundaries(rows,timeframe='daily',requested_start=date(2022,1,1),through=date(2022,1,7))==[
        {'symbol':'A','timeframe':'daily','start':'2022-01-01','end':'2022-01-03','reason':'BEFORE_FIRST_AVAILABLE_UNKNOWN'},
        {'symbol':'A','timeframe':'daily','start':'2022-01-07','end':'2022-01-07','reason':'AFTER_LAST_AVAILABLE_UNKNOWN'},
    ]

def test_missing_sessions_continue_after_last_record_through_requested_end():
    from orderflow.research.edge_data import missing_observations
    rows=[{'symbol':'A','session_date':date(2022,1,4),'ts':datetime(2022,1,4,tzinfo=timezone.utc)}]
    reference=[datetime(2022,1,d,tzinfo=timezone.utc) for d in (3,4,5,6)]
    missing=missing_observations(rows,reference,timeframe='daily',through=datetime(2022,1,6,23,59,tzinfo=timezone.utc))
    assert [row['start'] for row in missing]==['2022-01-05','2022-01-06']
    assert all(row['reason']=='AFTER_LAST_AVAILABLE_UNKNOWN_ON_OBSERVED_NIFTY_50_SESSION' for row in missing)

def test_naive_source_timestamp_is_rejected():
    with pytest.raises(ValueError,match='timezone'):
        normalize_candles([['2022-01-03T00:00:00',100,110,90,105,500,0]],symbol='A',instrument_key='K',timeframe='daily',source_sha256='s')
