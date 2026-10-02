"""T01 deterministic Upstox V3 snapshots and offline HTTP/transport failures."""
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from upstox_client.feeder.proto import MarketDataFeedV3_pb2 as pb


class SimulatedDisconnect(ConnectionError):
    """An explicit simulated transport disconnect, not a malformed data frame."""


@dataclass(frozen=True)
class Response:
    """Offline HTTP response; never performs an HTTP call."""
    status_code: int
    body: dict[str, Any]

    def json(self) -> dict[str, Any]:
        """Return the simulated response document."""
        return self.body


@dataclass
class SimulatedHTTP:
    """Section 5 T01: simulate 403 and expired token without real credentials."""
    scenario: str = 'normal'
    calls: list[dict[str, Any]] = field(default_factory=list)

    def request(self, method: str, endpoint: str, *, headers: dict[str, str],
                **kwargs: Any) -> Response:
        """Section 1 rule 1: reject every request missing an explicit User-Agent."""
        # Capture header names only; even synthetic credentials are not logged.
        self.calls.append(dict(method=method, endpoint=endpoint,
                               header_names=sorted(headers)))
        if not headers.get('User-Agent') or self.scenario == 'forbidden':
            return Response(403, {'error': 'Forbidden / Error 1010'})
        if self.scenario == 'expired_token':
            return Response(401, {'error': 'Token expired'})
        return Response(200, {'data': {'authorized_redirect_uri': 'simulator://feed'}})


@dataclass(frozen=True)
class FeedSimulator:
    """Section 5 T01: deterministic full-mode stock, index and VIX snapshots.

    One frame per second, tick-aligned trend or bounded range, increasing vtt,
    changing displayed quantities and sparse book depth. Faults occur at frame 3.
    No assumption that snapshots are individual trades is made.
    """
    start: datetime
    scenario: str = 'trend'
    depth: int = 5
    symbols: int = 1
    ist = ZoneInfo('Asia/Kolkata')

    def __post_init__(self) -> None:
        """Reject unsupported simulator configuration and naive timestamps."""
        if self.start.tzinfo is None or self.start.utcoffset() is None:
            raise ValueError('start must be timezone-aware')
        if self.depth not in (5, 30) or self.symbols < 1:
            raise ValueError('depth must be 5/30 and symbols positive')
        if self.scenario not in {'trend', 'range', 'gap', 'reset', 'duplicate',
                                 'out_of_order', 'disconnect'}:
            raise ValueError('unknown simulator scenario')

    @property
    def instruments(self) -> dict[str, str]:
        """Instrument key-to-symbol lookup, including context instruments."""
        stocks = {'NSE_EQ|TEST': 'TEST'} if self.symbols == 1 else {
            f'NSE_EQ|SIM{i:03}': f'SIM{i:03}' for i in range(self.symbols)}
        return {**stocks, 'NSE_INDEX|Nifty 50': 'NIFTY_50',
                'NSE_INDEX|Nifty Bank': 'BANK_NIFTY', 'NSE_INDEX|India VIX': 'INDIA_VIX'}

    def frames(self, count: int) -> Iterator[dict[str, Any]]:
        """Yield raw-message contract rows; disconnects are explicit exceptions."""
        if count < 0:
            raise ValueError('count must be nonnegative')
        previous: bytes | None = None
        for index in range(count):
            if self.scenario == 'disconnect' and index == 3:
                raise SimulatedDisconnect('simulated disconnect at frame 3')
            offset = index + (5 if self.scenario == 'gap' and index >= 3 else 0)
            if self.scenario == 'out_of_order' and index == 3:
                offset = 1
            event_ts = self.start + timedelta(seconds=offset)
            receipt_ts = self.start + timedelta(seconds=index, milliseconds=50)
            if self.scenario == 'gap' and index >= 3:
                receipt_ts += timedelta(seconds=5)
            message = pb.FeedResponse(currentTs=int(event_ts.timestamp() * 1000))
            for key in self.instruments:
                feed = message.feeds[key]
                if key.startswith('NSE_EQ'):
                    target = feed.fullFeed.marketFF
                    movement = (index % 8 - 4) if self.scenario == 'range' else index
                    price = Decimal('100') + Decimal('0.05') * movement
                    volume = 1000 + 10 * index
                    if self.scenario == 'reset' and index >= 3:
                        volume = 10 * (index - 3)
                    target.vtt = volume
                    target.oi = 0
                    target.tbq = sum(100 + level + index for level in range(self.depth))
                    target.tsq = sum(120 + level + index for level in range(self.depth))
                    for level in range(self.depth):
                        quote = target.marketLevel.bidAskQuote.add()
                        quote.bidP = float(price - Decimal('0.05') * (level + 1))
                        quote.askP = float(price + Decimal('0.05') * (level + 1))
                        quote.bidQ = 100 + level + index
                        quote.askQ = 120 + level + index
                else:
                    target = feed.fullFeed.indexFF
                    price = Decimal('20') if 'VIX' in key else Decimal('25000')
                    price += Decimal('0.05') * index
                target.ltpc.ltp = float(price)
                target.ltpc.ltt = message.currentTs
                target.ltpc.ltq = 10 if key.startswith('NSE_EQ') else 0
                target.ltpc.cp = float(price - 1)
            payload = message.SerializeToString(deterministic=True)
            if self.scenario == 'duplicate' and index == 3:
                assert previous is not None
                payload = previous
            previous = payload
            yield dict(connection_id='simulated-1', sequence=index, receipt_ts=receipt_ts,
                       payload=payload, source='SIMULATOR', flags=[])
