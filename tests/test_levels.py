"""T12 known answers and point-in-time level availability."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D

import pyarrow as pa
import pytest

from orderflow.layers.levels.core import levels
from orderflow.schema import BAR_SCHEMA, LEVEL_SCHEMA

UTC = timezone.utc
DAY = date(2026, 10, 1)


def bar(day, minute, *, opening=100, high=101, low=99, close=100,
        duration=1, delay=0, identifier=None):
    start = datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=3, minutes=45+minute)
    end = start + timedelta(minutes=duration)
    return dict(symbol='TEST', instrument_key='NSE_EQ|TEST', session_date=day,
        bar_id=identifier or f'{day}:{minute}', bar_kind='TIME', bar_start=start,
        bar_end=end, timeframe_minutes=duration, volume_target=None,
        open=D(str(opening)), high=D(str(high)), low=D(str(low)), close=D(str(close)),
        mid_close=None, volume=10, buy_volume=6, sell_volume=4, unknown_volume=0,
        delta=2, cvd=2, source='SIMULATOR', method='ESTIMATE', confidence='LOW',
        flags=[], available_at=end+timedelta(seconds=delay), inputs=[])


def table(rows):
    return pa.Table.from_pylist(rows, schema=BAR_SCHEMA)


def at(day=DAY, minute=30):
    return datetime.combine(day, datetime.min.time(), UTC)+timedelta(hours=3, minutes=45+minute)


def by_type(result):
    return {row['type']: row for row in result.to_pylist()}


def test_prior_day_and_completed_calendar_week_known_answers():
    rows = [bar(date(2026,9,24), 0, high=108, low=92, close=102),
            bar(date(2026,9,25), 0, high=110, low=95, close=105),
            bar(date(2026,9,30), 0, high=104, low=96, close=101),
            bar(DAY, 0, opening=103, high=104, low=102, close=103)]
    result=levels(table(rows), as_of=at(minute=1))
    assert result.schema.equals(LEVEL_SCHEMA)
    data=by_type(result)
    assert data['PDH']['low']==D('104') and data['PDL']['low']==D('96')
    assert data['PDC']['low']==D('101')
    assert data['PWH']['low']==D('110') and data['PWL']['low']==D('92')
    assert data['PDH']['available_at']==at(date(2026,9,30),375)
    assert 'INCOMPLETE_SESSION' in data['PDH']['flags']
    assert all(i['available_at'] <= r['available_at'] for r in result.to_pylist() for i in r['inputs'])


@pytest.mark.parametrize('window', [5,15,30])
def test_opening_range_not_available_until_window_closes(window):
    rows=[bar(DAY,i,high=101+i,low=99-i) for i in range(window)]
    before=by_type(levels(table(rows),as_of=at(minute=window)-timedelta(microseconds=1)))
    assert f'OR{window}_HIGH' not in before
    data=by_type(levels(table(rows),as_of=at(minute=window)))
    assert data[f'OR{window}_HIGH']['low']==D(100+window)
    assert data[f'OR{window}_LOW']['low']==D(100-window)
    assert data[f'OR{window}_HIGH']['available_at']==at(minute=window)


def test_late_bar_changes_availability_and_truncation_is_exact():
    rows=[bar(DAY,i,high=100+i,low=99,delay=60 if i==4 else 0) for i in range(7)]
    early=by_type(levels(table(rows),as_of=at(minute=5)))
    assert 'OR5_HIGH' not in early  # Missing bar could still be in flight.
    cutoff=at(minute=6)
    full=levels(table(rows),as_of=cutoff)
    truncated=levels(table([r for r in rows if r['available_at']<=cutoff]),as_of=cutoff)
    assert full.equals(truncated)
    assert by_type(full)['OR5_HIGH']['available_at']==cutoff


def test_gap_up_partial_fill_then_full_fill_after_confirming_bar():
    rows=[bar(date(2026,9,30),0,close=100),
          bar(DAY,0,opening=105,high=106,low=103,close=104),
          bar(DAY,1,opening=104,high=105,low=100,close=102)]
    first=by_type(levels(table(rows),as_of=at(minute=1)))['GAP']
    assert (first['low'],first['high'],first['state'],first['side'])==(D('100'),D('105'),'PARTIAL','SUPPORT')
    assert first['invalidated_at'] is None and first['origin_at']==at(minute=0)
    filled=by_type(levels(table(rows),as_of=at(minute=2)))['GAP']
    assert filled['state']=='FILLED' and filled['mitigated_at']==at(minute=2)
    assert filled['available_at']==at(minute=2)


def test_gap_down_fill_and_zero_gap():
    prior=bar(date(2026,9,30),0,close=100)
    data=by_type(levels(table([prior,bar(DAY,0,opening=95,high=100,low=94)]),as_of=at(minute=1)))
    assert data['GAP']['side']=='RESISTANCE' and data['GAP']['state']=='FILLED'
    no_gap=by_type(levels(table([prior,bar(DAY,0,opening=100)]),as_of=at(minute=1)))
    assert 'GAP' not in no_gap


def test_missing_range_bar_flagged_and_straddling_bar_never_used():
    missing=[bar(DAY,i,high=101+i) for i in range(5) if i!=2]
    data=by_type(levels(table(missing),as_of=at(minute=5)))
    assert 'OR5_HIGH' not in data
    assert 'GAP' in data['OR5_INCOMPLETE']['flags']
    assert data['OR5_INCOMPLETE']['state']=='INCOMPLETE'
    coarse=by_type(levels(table([bar(DAY,0,high=999,duration=15)]),as_of=at(minute=15)))
    assert 'OR5_HIGH' not in coarse and coarse['OR15_HIGH']['low']==D('999')


def test_round_numbers_disabled_by_default_and_require_explicit_interval():
    rows=table([bar(DAY,i,high=112,low=98) for i in range(5)])
    assert not any(r['type']=='ROUND_NUMBER' for r in levels(rows,as_of=at(minute=5)).to_pylist())
    result=levels(rows,as_of=at(minute=5),round_number_interval=D('5')).to_pylist()
    assert [r['low'] for r in result if r['type']=='ROUND_NUMBER']==[D('100'),D('105'),D('110')]
    with pytest.raises(ValueError,match='positive'):
        levels(rows,as_of=at(minute=5),round_number_interval=D('0'))


def test_prior_session_does_not_exist_before_its_close():
    same_day=table([bar(DAY,0)])
    assert 'PDH' not in by_type(levels(same_day,as_of=at(minute=1)))


def test_duplicate_bar_flag_is_local_and_never_backdates_its_receipt():
    rows=[bar(DAY,i) for i in range(5)]
    duplicate=dict(rows[-1]);duplicate['available_at']=at(minute=6)
    all_data=table([*rows,duplicate])
    early=by_type(levels(all_data,as_of=at(minute=5)))
    assert 'DUPLICATE' not in early['OR5_HIGH']['flags']
    late=by_type(levels(all_data,as_of=at(minute=6)))
    assert 'DUPLICATE' in late['OR5_HIGH']['flags']
    assert late['OR5_HIGH']['available_at']==at(minute=6)
    assert levels(all_data,as_of=at(minute=5)).equals(levels(table(rows),as_of=at(minute=5)))


def test_candle_contract_and_empty_and_naive_rejections():
    from orderflow.schema import CANDLE_SCHEMA
    rows=[bar(DAY,i) for i in range(5)]
    candles=pa.Table.from_pylist([{**r,'method':'APPROXIMATE'} for r in rows],schema=CANDLE_SCHEMA)
    result=by_type(levels(candles,as_of=at(minute=5)))
    assert result['OR5_HIGH']['method']=='APPROXIMATE'
    assert levels(table([]),as_of=at()).num_rows==0
    with pytest.raises(ValueError,match='aware'):
        levels(table(rows),as_of=datetime(2026,10,1,4))


def test_already_filled_gap_is_not_backdated_by_later_duplicate():
    prior=bar(date(2026,9,30),0,close=100)
    original=bar(DAY,0,opening=105,high=106,low=100)
    duplicate=dict(original);duplicate['available_at']=at(minute=3)
    data=table([prior,original,duplicate])
    gap=by_type(levels(data,as_of=at(minute=3)))['GAP']
    assert gap['available_at']==at(minute=1)
    assert 'DUPLICATE' not in gap['flags']
    assert by_type(levels(data,as_of=at(minute=1)))['GAP']==gap
