"""T00 Arrow contracts: timestamps, provenance and serialization requirements."""
from datetime import datetime, timezone
from decimal import Decimal
import tempfile
from pathlib import Path
import unittest
import pyarrow as pa
import pyarrow.parquet as pq
from orderflow.schema import SCHEMAS, DERIVED_SCHEMAS, TIMESTAMP, PRICE


class SchemaTests(unittest.TestCase):
    def test_registered_stage_contracts(self):
        self.assertEqual(set(SCHEMAS), {
            'instrument', 'raw_message', 'tick', 'candle', 'trade', 'bar',
            'footprint', 'feature', 'profile', 'level', 'context', 'zone',
            'event', 'setup', 'shadow_signal', 'outcome', 'quality',
        })
        for name, schema in SCHEMAS.items():
            with self.subTest(schema=name):
                self.assertIsInstance(schema, pa.Schema)
                self.assertEqual(schema.metadata[b'orderflow.schema_version'], b'1')
                self.assertEqual(len(schema.names), len(set(schema.names)))

    def test_timestamp_and_price_contracts(self):
        self.assertEqual(TIMESTAMP, pa.timestamp('us', tz='UTC'))
        self.assertEqual(PRICE, pa.decimal128(24, 8))
        for name, schema in SCHEMAS.items():
            for field in schema:
                if pa.types.is_timestamp(field.type):
                    self.assertEqual(field.type.tz, 'UTC', (name, field.name))
        for name in DERIVED_SCHEMAS:
            schema = SCHEMAS[name]
            self.assertEqual(schema.field('available_at').type, TIMESTAMP)
            self.assertFalse(schema.field('available_at').nullable)
            for field in ('source', 'method', 'confidence', 'flags'):
                self.assertIn(field, schema.names)

    def test_tick_preserves_depth_and_quality_flags(self):
        schema = SCHEMAS['tick']
        now = datetime(2026, 10, 1, 3, 45, tzinfo=timezone.utc)
        row = dict(symbol='TEST', instrument_key='NSE_EQ|TEST', session_date=now.date(),
                   sequence=1, ltp=Decimal('100.05'), ltq=10, ltt=now, vtt=1000,
                   oi=None, bids=[dict(price=Decimal('100'), quantity=20, orders=2)],
                   asks=[dict(price=Decimal('100.10'), quantity=30, orders=3)],
                   tbq=20, tsq=30, exchange_ts=now, receipt_ts=now,
                   source='SIMULATOR', flags=['FIRST_TICK', 'GAP'])
        table = pa.Table.from_pylist([row], schema=schema)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'part-00001.parquet'
            pq.write_table(table, path)
            restored = pq.read_table(path)
        self.assertTrue(restored.equals(table))
        self.assertEqual(restored.to_pylist()[0]['flags'], ['FIRST_TICK', 'GAP'])

    def test_derived_trade_reports_unknown_separately(self):
        schema = SCHEMAS['trade']
        for name in ('volume', 'side', 'quote_ts', 'available_at', 'method', 'confidence'):
            self.assertIn(name, schema.names)
        for name in ('unknown_volume', 'buy_volume', 'sell_volume'):
            self.assertIn(name, SCHEMAS['bar'].names)

    def test_arrow_ipc_preserves_every_schema(self):
        for name, schema in SCHEMAS.items():
            with self.subTest(schema=name):
                restored = pa.ipc.read_schema(pa.BufferReader(schema.serialize()))
                self.assertTrue(restored.equals(schema, check_metadata=True))


if __name__ == '__main__':
    unittest.main()
