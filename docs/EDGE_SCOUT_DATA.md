# EXPLORATORY public-data audit

This research uses unauthenticated GET requests to Upstox's public instrument file and Historical Candle V3 endpoint. Successful 200 responses were verified empirically without an Authorization header. Upstox's [V3 documentation](https://upstox.com/developer/api-documentation/v3/get-historical-candle-data/) states daily availability from January 2000 and hourly availability from January 2022, with request ranges of ten years and one quarter respectively. The script also probes 1990–1999 and reports its empty responses separately; that does not extend documented retention.

The universe is the current official Nifty 200 constituent CSV, mapped by ISIN to `NSE_EQ` instruments, plus the current Nifty 50 constituent CSV. This introduces survivorship bias: historical index membership, delisted securities and formerly included stocks are absent. Sector labels are current labels, not historical classifications. Sector-index archives may contain backcasts predating index launch; the endpoint does not prove that each historical value or its constituent set was publicly available on the stated candle date. Such benchmarks require independent point-in-time verification before local validation.

Industry-relative comparisons use the listed industry-to-index proxies in `SECTORS` in `edge_data.py`. Capital goods, construction, construction materials and telecommunications use Nifty Infra; consumer durables, consumer services and textiles use Nifty Consumption; services use Nifty Services Sector. These broad proxies are disclosed, not represented as exact sector benchmarks. Financial services uses Nifty Financial Services, not the banking-only index.

Every request sends an explicit User-Agent, permits at most five requests per second, and retries once with backoff. The immutable raw-response cache stores the URL, fetch time and SHA-256. A cached body must match its hash before reuse. Parquet tables contain canonical UTC timestamps, original `source_ts`, source hashes, `quality_flags`, and availability timestamps: daily timestamps are normalized by session date to 00:00 Asia/Kolkata because the source mixes midnight, morning and noon timestamps; daily OHLCV is available only at 15:30 Asia/Kolkata; regular hourly candles become available at their close, with the final 15:15 candle capped at 15:30. Special evening candles are retained and audited with an availability timestamp after their start. Once hourly data is complete, observed Nifty 50 evening-session closes delay the corresponding daily availability timestamp. Before 2022, special-session close times remain unverified; these archives are intended for next-session entries, and the report excludes verified special sessions from regular panels.

OHLCV corporate-action adjustment status is **UNVERIFIED**. No official adjustment factor was supplied by these endpoints. Raw jumps must not be assumed to be either tradable returns or correctly adjusted split histories. Dividends are not included, and current instruments/ISINs can omit earlier symbol or corporate-history records. The main report must apply and disclose its independent corporate-action safeguards.

Missing symbol-periods and intraperiod missing observations are listed in `EDGE_SCOUT_MISSING.csv`; dates before each instrument's first record are left censored and are not silently treated as missing sessions. A gap against Nifty 50's observed session calendar can reflect suspension, a symbol-history change or a download problem. A missing weekday in the index can reflect a holiday or data outage and is not, by itself, an official holiday declaration.

## Download coverage

Daily download is complete: **200 equities plus 14 indices, 946,598 canonical daily rows**, through 2026-10-01. The source included 1,032 duplicate session rows; 569 duplicate observations had conflicting OHLCV values, affecting **565 distinct session rows** that remain explicitly flagged for exclusion by the backtester. A further 533 raw daily observations failed OHLCV validity checks; their omission is audited, not silently filled. The daily audit finds 8,269 absent observations inside each instrument's first/last coverage against Nifty 50's observed calendar. For example, SBICARD contains a disconnected 2015 block followed by its 2020 history, and 360ONE has an older disconnected block. These gaps expose potentially spliced legacy instrument history and must not be bridged by indicators. Nifty 50 supplied records from 1990-07-03, before its later launch; this index history may be backcast and is not represented as a tradable contemporary instrument.

Hourly download is complete: **1,656,534 rows across the same 214 instruments**, from 2022-01-03 through 2026-10-01. Eleven invalid raw hourly observations are counted, and the matching 11 missing index-reference timestamps are listed. There are no missing entire hourly sessions inside coverage. The 596 rows outside the regular session remain in the cache with `OUTSIDE_REGULAR_SESSION`; the engine excludes verified special sessions and nonstandard starts from its regular panels. Observed evening index closes delayed availability for 596 daily rows.

All **5,139 public requests succeeded with HTTP 200**. Bodies were fetched between 2026-10-02T18:03:58.972537+00:00 and 2026-10-02T18:35:37.788507+00:00. No token, OAuth, websocket or authenticated fallback was used.

The missing audit contains **9,807 records**: 534 empty symbol-period responses, 8,269 daily absent-session observations, 428 unknown leading-coverage ranges, 565 unresolved conflicting daily rows and 11 absent hourly timestamps. Ranges can overlap empty windows and include weekends before the first candle; this is an audit-record count, **not** a count of lost trading days. No trailing unknown ranges remain because every populated series reaches 2026-10-01. Leading ranges are labelled `BEFORE_FIRST_AVAILABLE_UNKNOWN`, not guessed listing dates. Trailing ranges and absent sessions after a last record are explicitly supported by the audit and tested.

| Cached file | Rows | SHA-256 |
|---|---:|---|
| `data/edge_scout/candles_daily.parquet` | 946,598 | `f337ec6854ec2f0921c7b0a781ba1b63bb59863b52f385fc208ff8283345a784` |
| `data/edge_scout/candles_hourly.parquet` | 1,656,534 | `7a31e5578e3f8ae5a5abf2bbbe7919e7d7f3e9f532f0caa5fe1aa30fd00e6dcc` |

The raw response manifest, per-symbol canonical shards, raw quality counters, observed session calendar and availability-alignment provenance remain under the gitignored cache. The authoritative consolidated daily table contains the subsequent index-session availability refinement; raw-normalized daily shards retain the initial regular-close assumption.

## Reproduce the cache

```bash
PYTHONPATH=src python -m orderflow.research.edge_data --through 2026-10-01
pytest -q tests/test_edge_data.py
```

The downloader uses no authentication or tokens. Its public HTTP session explicitly disables implicit netrc credentials and Authorization headers, including redirects. `data/` is gitignored; raw candles and instruments are not committed. Existing SHA-verified responses are reused and corrupted responses are fetched again.
