"""T06 footprint, diagonal/stacked imbalance and point-in-time known answers."""
from datetime import timedelta
from decimal import Decimal as D
import pyarrow as pa
from orderflow.layers.orderflow.footprint import footprint,diagonal,stacked
from orderflow.bars.core import time_bars
from orderflow.trades.core import classify_ticks
from test_trades_bars import ticks,START


def test_diagonal_exact_known_answer_and_zero_opposite():
    levels={D('100'):{'bid':5,'ask':60},D('100.05'):{'bid':10,'ask':20},
            D('100.10'):{'bid':1,'ask':35}}
    buys,sells=diagonal(levels,tick_size=D('.05'),ratio=3,min_volume=20)
    assert buys=={D('100'),D('100.05'),D('100.10')}
    assert sells==set()


def test_stacked_needs_three_adjacent_same_side_levels():
    assert stacked({D('100'),D('100.05'),D('100.10')},tick_size=D('.05'),count=3)=={D('100'),D('100.05'),D('100.10')}
    assert stacked({D('100'),D('100.05'),D('100.15')},tick_size=D('.05'),count=3)==set()


def test_footprint_sell_maps_to_bid_buy_to_ask_and_unknown_separate():
    data=classify_ticks(ticks([(100,0,99,101,[]),(101,10,99,101,[]),(99,30,99,101,[])]))
    bars=time_bars(data,minutes=1,as_of=START+timedelta(minutes=1))
    out=footprint(data,bars,tick_size=D('.05')).to_pylist()
    levels={row['price']:row for row in out}
    assert levels[D('101')]['ask_volume']==10 and levels[D('101')]['bid_volume']==0
    assert levels[D('99')]['bid_volume']==20 and levels[D('99')]['ask_volume']==0
    assert all(row['method']=='ESTIMATE' for row in out)


def test_footprint_truncation_and_late_trade_cannot_change_closed_bar():
    data=classify_ticks(ticks([(100+i*.05,10*i,99,101,[]) for i in range(12)]))
    short=data.slice(0,6)
    bars=time_bars(data,minutes=1,as_of=START+timedelta(minutes=1))
    assert footprint(data,bars,tick_size=D('.05')).equals(footprint(short,bars,tick_size=D('.05')))


def test_volume_bar_footprint_uses_allocated_snapshot_parts():
    from orderflow.bars.core import volume_bars
    data=classify_ticks(ticks([(100,0,None,None,[]),(100,25,None,None,[])]))
    bars=volume_bars(data,target=10,as_of=START+timedelta(minutes=1))
    out=footprint(data,bars,tick_size=D('.05')).to_pylist()
    assert len(out)==2 and [r['unknown_volume'] for r in out]==[10,10]


def test_overlapping_timeframes_do_not_double_count_daily_threshold():
    data=classify_ticks(ticks([(100,0,99,101,[]),(101,10,99,101,[]),(99,30,99,101,[])]))
    one=time_bars(data,minutes=1,as_of=START+timedelta(minutes=5))
    five=time_bars(data,minutes=5,as_of=START+timedelta(minutes=5))
    combined=footprint(data,pa.concat_tables([one,five]),tick_size=D('.05')).to_pylist()
    singles=footprint(data,five,tick_size=D('.05')).to_pylist()
    assert [r for r in combined if r['bar_id']==five.to_pylist()[0]['bar_id']]==singles
