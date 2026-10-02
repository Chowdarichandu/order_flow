"""Official V3 protobuf to the canonical TickEvent Arrow contract."""
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow as pa
from upstox_client.feeder.proto import MarketDataFeedV3_pb2 as pb
from orderflow.schema import TICK_SCHEMA

UTC = timezone.utc
IST = ZoneInfo('Asia/Kolkata')


class Decoder:
    """Section 5 T01 decoder; section 1 rule 11 preserves and counts anomalies.

    Quality baselines advance only for non-stale snapshots, independently per
    instrument/session. Identical snapshots are not assumed to be trades. A
    duplicate is an identical protobuf instrument payload at the same feed time.
    Gap threshold is explicit, not evidence of missing individual trades.
    """

    def __init__(self, instruments: dict[str, str], *, gap_seconds: float = 2) -> None:
        self.instruments = dict(instruments)
        if gap_seconds <= 0:
            raise ValueError('gap_seconds must be positive')
        self.gap_seconds = gap_seconds
        self.counters: Counter[str] = Counter()
        self._last: dict[tuple[str, Any], tuple[datetime, int | None, bytes]] = {}

    def decode(self, frame: dict[str, Any]) -> pa.Table:
        """Section 3: preserve V3 prices/depth, ltt/vtt, exchange and receipt times.

        IndexFullFeed does not carry market volume/depth; preserve absence as
        null/empty, rather than fabricate stock-like data. Order count is absent
        from V3 Quote and remains null. ltpc-only/greeks feeds are supported too.
        """
        receipt = frame['receipt_ts']
        if receipt.tzinfo is None or receipt.utcoffset() is None:
            raise ValueError('receipt_ts must be timezone-aware')
        receipt = receipt.astimezone(UTC)
        message = pb.FeedResponse.FromString(frame['payload'])
        exchange = datetime.fromtimestamp(message.currentTs / 1000, UTC) if message.currentTs else None
        rows = []
        for key in sorted(message.feeds):
            if key not in self.instruments:
                raise ValueError(f'unknown instrument: {key}')
            feed = message.feeds[key]
            kind = feed.WhichOneof('FeedUnion')
            market = None
            levels = []
            if kind == 'fullFeed':
                full_kind = feed.fullFeed.WhichOneof('FullFeedUnion')
                if full_kind == 'marketFF':
                    market = feed.fullFeed.marketFF
                    ltpc = market.ltpc
                    levels = list(market.marketLevel.bidAskQuote)
                elif full_kind == 'indexFF':
                    ltpc = feed.fullFeed.indexFF.ltpc
                else:
                    raise ValueError('unsupported empty FullFeed')
            elif kind == 'ltpc':
                ltpc = feed.ltpc
            elif kind == 'firstLevelWithGreeks':
                market = feed.firstLevelWithGreeks
                ltpc = market.ltpc
                levels = [market.firstDepth]
            else:
                raise ValueError('unsupported empty feed variant')
            day = (exchange or receipt).astimezone(IST).date()
            volume = market.vtt if market is not None else None
            flags = list(frame['flags'])
            state_key = (key, day)
            signature = feed.SerializeToString(deterministic=True)
            prior = self._last.get(state_key)
            if prior is None:
                flags.append('FIRST_TICK')
            elif exchange is not None:
                last_ts, last_volume, last_bytes = prior
                if exchange < last_ts:
                    flags.append('OUT_OF_ORDER')
                elif exchange == last_ts and signature == last_bytes:
                    flags.append('DUPLICATE')
                else:
                    if (exchange - last_ts).total_seconds() > self.gap_seconds:
                        flags.append('GAP')
                    if volume is not None and last_volume is not None and volume < last_volume:
                        flags.append('VOLUME_RESET')
            for flag in flags:
                self.counters[flag] += 1
            if exchange is not None and 'OUT_OF_ORDER' not in flags and 'DUPLICATE' not in flags:
                self._last[state_key] = (exchange, volume, signature)
            bids = [dict(price=Decimal(str(q.bidP)), quantity=q.bidQ, orders=None)
                    for q in levels if q.bidP > 0]
            asks = [dict(price=Decimal(str(q.askP)), quantity=q.askQ, orders=None)
                    for q in levels if q.askP > 0]
            rows.append(dict(
                symbol=self.instruments[key], instrument_key=key, session_date=day,
                sequence=frame['sequence'], ltp=Decimal(str(ltpc.ltp)), ltq=ltpc.ltq,
                ltt=datetime.fromtimestamp(ltpc.ltt / 1000, UTC) if ltpc.ltt else None,
                vtt=volume, oi=int(market.oi) if market is not None else None,
                bids=bids, asks=asks,
                tbq=int(market.tbq) if market is not None and hasattr(market, 'tbq') else None,
                tsq=int(market.tsq) if market is not None and hasattr(market, 'tsq') else None,
                exchange_ts=exchange, receipt_ts=receipt, source=frame['source'], flags=flags))
        return pa.Table.from_pylist(rows, schema=TICK_SCHEMA)
