"""T03 bounded nonblocking receive queue and crash-safe writer thread."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import fcntl
import json
import logging
import os
from pathlib import Path
from queue import Queue, Empty, Full
import threading
from time import monotonic
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import pyarrow as pa
import pyarrow.parquet as pq
from orderflow.schema import RAW_MESSAGE_SCHEMA, TICK_SCHEMA
from orderflow.auth.core import aware, sanitized_body, secure_json

LOG = logging.getLogger(__name__)


class FeedLock:
    """Section 1 rule 6: process-scoped flock permits only one feed owner."""
    def __init__(self, path: Path):
        self.path, self.handle = Path(path), None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open('a')
        try:
            fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.handle.close()
            raise RuntimeError('another recorder owns the feed') from None
        return self

    def __exit__(self, *args):
        if self.handle:
            self.handle.close()


class Recorder:
    """Section 1 rule 3: receive -> bounded queue -> batched writer thread.

    Multiplexed protobuf packets stay intact under raw/IST-date. No decode or
    file write occurs in receive. Overflow is explicit, counted and logged.
    Files are individually fsynced and atomically renamed; SIGKILL may lose
    queued data, which cannot be made durable without violating the receive
    rule. A normal shutdown flushes every enqueued frame or reports failure.
    """
    def __init__(self, root: Path, *, capacity: int = 25000, batch_size: int = 1000,
                 flush_seconds: float = 1, decoder: Any = None, on_flush: Any = None):
        if min(capacity, batch_size) < 1 or flush_seconds <= 0:
            raise ValueError('invalid recorder batching policy')
        self.root, self.batch_size, self.flush_seconds = Path(root), batch_size, flush_seconds
        self.queue: Queue = Queue(maxsize=capacity)
        self.metrics: Counter = Counter(received=0, written=0, dropped=0, disconnects=0,
                                        max_queue_lag_ms=0, max_exchange_lag_ms=0,
                                        negative_exchange_lag_count=0, max_clock_skew_ms=0,
                                        missing_exchange_timestamps=0, decode_failures=0)
        self.decoder = decoder
        self.on_flush = on_flush
        self.error: Exception | None = None
        self.thread: threading.Thread | None = None
        self.closed = False

    def receive(self, frame: dict[str, Any]) -> bool:
        """Enqueue without blocking or disk I/O; return False on counted overflow."""
        if self.closed:
            raise RuntimeError('recorder closed')
        if self.error:
            raise RuntimeError('writer failed') from self.error
        self.metrics['received'] += 1
        try:
            self.queue.put_nowait((dict(frame), monotonic()))
            return True
        except Full:
            self.metrics['dropped'] += 1
            LOG.error('recorder queue overflow drop_count=%d', self.metrics['dropped'])
            return False

    def start(self) -> None:
        """Start the sole writer; never spawn a writer per websocket connection."""
        if self.thread is not None:
            raise RuntimeError('writer already started')
        self.thread = threading.Thread(target=self._writer, name='orderflow-writer', daemon=True)
        self.thread.start()

    def _flush(self, batch: list[dict[str, Any]]) -> None:
        """Group packets by IST receipt date; fsync/rename every batch part."""
        groups: dict[str, list[dict]] = {}
        for frame in batch:
            if self.decoder is not None:
                try:
                    decoded = self.decoder.decode(frame)
                    if not decoded.schema.equals(TICK_SCHEMA):
                        raise ValueError('canonical TickEvent schema required')
                    # Quality/lag analysis belongs to the writer, never receive.
                    # Count skew per decoded instrument snapshot, not per packet.
                    for receipt, exchange in zip(decoded['receipt_ts'].to_pylist(),
                                                 decoded['exchange_ts'].to_pylist()):
                        if exchange is None:
                            self.metrics['missing_exchange_timestamps'] += 1
                            continue
                        lag = (aware(receipt)-aware(exchange)).total_seconds()*1000
                        if lag < 0:
                            self.metrics['negative_exchange_lag_count'] += 1
                            self.metrics['max_clock_skew_ms'] = max(
                                self.metrics['max_clock_skew_ms'], -lag)
                        else:
                            self.metrics['max_exchange_lag_ms'] = max(
                                self.metrics['max_exchange_lag_ms'], lag)
                except Exception:
                    self.metrics['decode_failures'] += 1
                    frame['flags'] = [*frame['flags'], 'DECODE_ERROR']
            day = frame['receipt_ts'].astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat()
            groups.setdefault(day, []).append(frame)
        for day, frames in groups.items():
            folder = self.root / 'raw' / day
            folder.mkdir(parents=True, exist_ok=True)
            destination = folder / f'part-{uuid4().hex}.parquet'
            temp = destination.with_suffix('.tmp')
            try:
                pq.write_table(pa.Table.from_pylist(frames, schema=RAW_MESSAGE_SCHEMA), temp)
                with temp.open('rb') as handle:
                    os.fsync(handle.fileno())
                os.replace(temp, destination)
                fd = os.open(folder, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
                self.metrics['written'] += len(frames)
            finally:
                if temp.exists():
                    temp.unlink()

        if self.on_flush is not None:
            try:
                self.on_flush(self.quality())
            except Exception:
                LOG.warning('status update failed (soft alert)')

    def _writer(self) -> None:
        """Write batches off the receive thread; save errors for shutdown/reporting."""
        batch = []
        last_flush = monotonic()
        try:
            while True:
                try:
                    item = self.queue.get(timeout=self.flush_seconds)
                except Empty:
                    item = 'timeout'
                if item is None:
                    if batch:
                        self._flush(batch)
                    return
                if item != 'timeout':
                    frame, enqueued = item
                    self.metrics['max_queue_lag_ms'] = max(
                        self.metrics['max_queue_lag_ms'], (monotonic()-enqueued)*1000)
                    batch.append(frame)
                if batch and (len(batch) >= self.batch_size or monotonic()-last_flush >= self.flush_seconds):
                    self._flush(batch)
                    batch = []
                    last_flush = monotonic()
        except Exception as error:
            self.error = error
            LOG.error('writer failed: disk operation unsuccessful')

    def close(self) -> None:
        """Drain on graceful shutdown; writer failure raises instead of hanging."""
        if self.closed:
            return
        self.closed = True
        if self.thread is None:
            self.start()
        while self.thread.is_alive() and self.error is None:
            try:
                self.queue.put(None, timeout=.05)
                break
            except Full:
                continue
        self.thread.join(timeout=30)
        if self.error is not None or self.thread.is_alive():
            raise RuntimeError('writer failed or shutdown timed out') from self.error

    def quality(self, counters: Counter | None = None) -> dict[str, Any]:
        """Daily quality: drops, anomalies, queue lag and receipt-exchange lag.

        Exchange lag is the maximum nonnegative receipt-minus-exchange duration
        over decoded snapshots in UTC, independent of local queue waiting time.
        Future exchange clocks are counted separately with maximum skew size.
        Without a decoder, exchange metrics are unobserved and stay zero.
        """
        c = counters if counters is not None else (self.decoder.counters if self.decoder is not None else Counter())
        return dict(self.metrics, gaps=c['GAP'], resets=c['VOLUME_RESET'],
                    duplicates=c['DUPLICATE'], out_of_order=c['OUT_OF_ORDER'],
                    unwritten=self.metrics['received']-self.metrics['written']-self.metrics['dropped'])

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.close()


class FeedClient:
    """Section 3: authorize/connect/subscribe/reconnect through injected adapters."""
    def __init__(self, api: Any, connect: Any, recorder: Recorder, *,
                 instruments: list[str], mode: str = 'full', retry_seconds: float = 3):
        if not instruments or mode not in ('ltpc', 'full', 'full_d30'):
            raise ValueError('instrument list and supported feed mode required')
        self.api, self.connect, self.recorder = api, connect, recorder
        self.instruments, self.mode, self.retry_seconds = instruments, mode, retry_seconds
        self.stopped = False

    def _log_failure(self, error: Exception) -> None:
        """Rule 4: retain known handshake status/body with credential redaction.

        Current websockets InvalidStatus exposes response.status_code/body;
        legacy adapters may expose status_code/body directly. Exception strings,
        response URLs and websocket URLs are never logged. A token is read only
        from the secure credential file for redaction, including after expiry.
        """
        response = getattr(error, 'response', None)
        raw_status = getattr(response, 'status_code', None)
        if raw_status is None:
            raw_status = getattr(error, 'status_code', None)
        status = (str(raw_status) if isinstance(raw_status, int)
                  and 100 <= raw_status <= 599 else 'unavailable')
        body = getattr(response, 'body', None)
        if body is None:
            body = getattr(error, 'body', None)
        if body is None and response is not None:
            body = getattr(response, 'text', None)
        if body is None:
            body = 'connection failed' if status == 'unavailable' else 'response body unavailable'
        if isinstance(body, (bytes, bytearray)):
            body = bytes(body).decode('utf-8', errors='replace')
        if not isinstance(body, (str, dict, list)):
            body = 'response body unavailable'
        secrets: tuple[str, ...] = ()
        token_file = getattr(self.api, 'token_file', None)
        token_path = getattr(token_file, 'path', None)
        if token_path is not None:
            try:
                token = secure_json(Path(token_path)).get('access_token')
                if isinstance(token, str):
                    secrets = (token,)
            except Exception:
                # Unsafe/unreadable credentials are never printed or bypassed.
                pass

        class Body:
            """Local response adapter for the shared JSON/plaintext sanitizer."""
            text = body

            def json(self) -> Any:
                return json.loads(body) if isinstance(body, str) else body

        LOG.error('connect/stream failure status=%s body=%s', status,
                  sanitized_body(Body(), secrets))

    async def run(self, *, max_connections: int | None = None) -> None:
        """One socket at a time; reconnect rereads authorization and resubscribes.

        The adapter owns ping/pong heartbeat and timeout settings. Only bytes and
        receipt time enter the queue; this receive loop never writes to disk.
        """
        connections, sequence = 0, 0
        while not self.stopped and (max_connections is None or connections < max_connections):
            socket = None
            connections += 1
            connection_id = uuid4().hex
            connection_frames = 0
            try:
                url = self.api.authorize()
                socket = await self.connect(url)
                request = dict(guid=uuid4().hex, method='sub', data=dict(
                    mode=self.mode, instrumentKeys=self.instruments))
                await socket.send(json.dumps(request).encode())
                async for payload in socket:
                    if self.stopped:
                        break
                    if not isinstance(payload, bytes):
                        self.recorder.metrics['nonbinary_messages'] += 1
                        continue
                    self.recorder.receive(dict(connection_id=connection_id, sequence=sequence,
                        receipt_ts=datetime.now(timezone.utc), payload=payload, source='UPSTOX_V3',
                        flags=['RECONNECT'] if connections > 1 and connection_frames == 0 else []))
                    sequence += 1
                    connection_frames += 1
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.recorder.metrics['disconnects'] += 1
                self._log_failure(error)
                if self.recorder.error:
                    raise RuntimeError('writer failed') from self.recorder.error
            finally:
                if socket is not None:
                    await socket.close()
            if not self.stopped and (max_connections is None or connections < max_connections):
                await asyncio.sleep(self.retry_seconds)
