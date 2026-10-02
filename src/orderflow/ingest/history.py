"""T05 injectable V3 history downloader and deterministic raw recording import."""
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from time import sleep as real_sleep
from typing import Any
from urllib.parse import quote

import pyarrow as pa
import pyarrow.parquet as pq
from orderflow.auth.core import atomic_file
from orderflow.decode.candles import decode_candles
from orderflow.schema import RAW_MESSAGE_SCHEMA, TICK_SCHEMA, CANDLE_SCHEMA


def write_table_atomic(table: pa.Table, path: Path) -> None:
    """Persist canonical Arrow table with atomic rename + file/directory fsync."""
    stream = pa.BufferOutputStream()
    pq.write_table(table, stream)
    atomic_file(path, stream.getvalue().to_pybytes())


class HistoryDownloader:
    """Section 2: resumable 1-minute Historical Candle V3 from January 2022.

    Api supplies explicit User-Agent and token reread. Per-day requests keep V3
    range limits bounded. Failures/gaps are recorded, not imputed; successful
    cached files are hash-verified. Clock, throttle and transport are injected.
    """
    def __init__(self, api: Any, root: Path, *,
                 now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 sleep: Callable[[float], None] = real_sleep,
                 throttle_seconds: float = .2, attempts: int = 2):
        if attempts < 1 or throttle_seconds < 0:
            raise ValueError('invalid download policy')
        self.api,self.root,self.now,self.sleep = api,Path(root),now,sleep
        self.throttle_seconds,self.attempts = throttle_seconds,attempts
        self.manifest_path = self.root/'history/manifest.json'
        self.manifest = json.loads(self.manifest_path.read_text()) if self.manifest_path.exists() else {}

    def _save(self) -> None:
        atomic_file(self.manifest_path,json.dumps(self.manifest,sort_keys=True,indent=2).encode())

    def day(self, symbol: str, instrument_key: str, day: date, *,
            is_trading_day: Callable[[date], bool] | None = None) -> str:
        """Request one trading day; gap/holiday/error status is explicit and resumable."""
        if is_trading_day and not is_trading_day(day):
            return 'HOLIDAY'
        key = instrument_key+':'+day.isoformat()
        existing = self.manifest.get(key,{})
        file = self.root/'history'/sha256(instrument_key.encode()).hexdigest()[:16]/(day.isoformat()+'.parquet')
        if existing.get('state') == 'DONE' and file.exists():
            if sha256(file.read_bytes()).hexdigest() == existing.get('sha256'):
                return 'CACHED'
        path = '/v3/historical-candle/'+quote(instrument_key,safe='')+'/minutes/1/'+day.isoformat()+'/'+day.isoformat()
        for attempt in range(self.attempts):
            self.sleep(self.throttle_seconds)
            try:
                response = self.api.request('GET',path).json()
                table = decode_candles(response,symbol=symbol,instrument_key=instrument_key,
                                       receipt_ts=self.now())
                if table.num_rows == 0:
                    self.manifest[key] = {'state':'GAP','reason':'empty response'}
                    self._save()
                    return 'GAP'
                flags = sorted({flag for row in table.to_pylist() for flag in row['flags']})
                write_table_atomic(table,file)
                self.manifest[key] = dict(state='DONE',file=str(file.relative_to(self.root)),
                    rows=table.num_rows,quality_flags=flags,sha256=sha256(file.read_bytes()).hexdigest())
                self._save()
                return 'DONE'
            except Exception:
                if attempt+1 == self.attempts:
                    self.manifest[key] = {'state':'ERROR','reason':'download or decode failure'}
                    self._save()
                    return 'ERROR'
        raise AssertionError('unreachable')

    def range(self, symbol: str, instrument_key: str, start: date, end: date, *,
              is_trading_day: Callable[[date],bool] | None = None) -> dict[str,int]:
        """Inclusive day range, default owner start date is 2022-01-01."""
        from collections import Counter
        if end < start:
            raise ValueError('end before start')
        counts = Counter()
        while start <= end:
            counts[self.day(symbol,instrument_key,start,is_trading_day=is_trading_day)] += 1
            start += timedelta(days=1)
        return dict(counts)


def cross_check(candles: pa.Table, bhavcopy: dict[str,Any]) -> dict[str,Any]:
    """Section 2: compare candle daily OHLCV with official bhavcopy; never repair."""
    if not candles.schema.equals(CANDLE_SCHEMA):
        raise ValueError('canonical candle schema required')
    rows = sorted(candles.to_pylist(),key=lambda row:row['bar_start'])
    if not rows:
        raise ValueError('empty candle set')
    daily = dict(volume=sum(r['volume'] for r in rows), high=max(r['high'] for r in rows),
                 low=min(r['low'] for r in rows),close=rows[-1]['close'],open=rows[0]['open'])
    from decimal import Decimal
    differences = {name:float(daily[name])-float(bhavcopy[name]) for name in daily if name in bhavcopy}
    return dict(matches=all(value == 0 for value in differences.values()),
                volume_difference=differences.get('volume'),differences=differences,
                method='CROSS_CHECK', delivery_percent=bhavcopy.get('delivery_percent'))


def import_recordings(source: Path, target: Path, decoder: Any) -> dict[str,int]:
    """Section 2/T05: hash-idempotent import of canonical raw/tick/candle Parquet.

    Raw protobuf frames replay in sequence order through the same V3 decoder;
    raw bytes are preserved. Unknown legacy formats require an explicit adapter
    and are rejected; timestamps/column meanings are never guessed.
    """
    source,target=Path(source),Path(target)
    if target.resolve().is_relative_to(source.resolve()):
        raise ValueError('import target cannot be inside the source')
    files=sorted(source.rglob('*.parquet'))
    schemas={}
    for file in files:
        schema=pq.ParquetFile(file).schema_arrow
        if not any(schema.equals(known) for known in (RAW_MESSAGE_SCHEMA,TICK_SCHEMA,CANDLE_SCHEMA)):
            raise ValueError(f'unknown recording schema: {file.name}; explicit adapter required')
        schemas[file]=schema
    path=target/'imports/manifest.json'
    manifest=json.loads(path.read_text()) if path.exists() else {}
    stats=dict(frames=0,ticks=0,skipped=0,files=0)
    pending=[]
    for file in files:
        digest=sha256(file.read_bytes()).hexdigest()
        if digest in manifest:
            stats['skipped']+=1
            continue
        pending.append((file,digest))
    # Global receipt/connection/sequence order permits deterministic cross-part replay.
    raw_rows=[]
    for file,digest in pending:
        table=pq.ParquetFile(file).read()
        if schemas[file].equals(RAW_MESSAGE_SCHEMA):
            raw_rows.extend(table.to_pylist())
            write_table_atomic(table,target/'raw'/'imported'/f'part-{digest}.parquet')
            stats['frames']+=table.num_rows
        elif schemas[file].equals(TICK_SCHEMA):
            write_table_atomic(table,target/'ticks'/'imported'/f'part-{digest}.parquet')
            stats['ticks']+=table.num_rows
        else:
            write_table_atomic(table,target/'history'/'imported'/f'part-{digest}.parquet')
        stats['files']+=1
    if raw_rows:
        raw_rows.sort(key=lambda r:(r['receipt_ts'],r['connection_id'],r['sequence']))
        batches=[]
        for frame in raw_rows:
            batches.append(decoder.decode(frame))
            if len(batches) >= 1000:
                table=pa.concat_tables(batches);stats['ticks']+=table.num_rows
                key=sha256(''.join(d for _,d in pending).encode()).hexdigest()+f'-{stats["ticks"]}'
                write_table_atomic(table,target/'ticks'/'imported'/f'part-{key}.parquet')
                batches=[]
        if batches:
            table=pa.concat_tables(batches);stats['ticks']+=table.num_rows
            key=sha256(''.join(d for _,d in pending).encode()).hexdigest()+f'-{stats["ticks"]}'
            write_table_atomic(table,target/'ticks'/'imported'/f'part-{key}.parquet')
    for file,digest in pending:
        manifest[digest]=str(file)
    atomic_file(path,json.dumps(manifest,sort_keys=True,indent=2).encode())
    return stats
