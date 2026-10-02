# Upstox data sources

  Source                           Gives                              Used by

  Market Data Feed V3              ltp, ltq, ltt, cumulative volume   order flow, tick volume
  websocket (full mode; 30-        (vtt), OI, best 5 bid/ask, total   profile, live VWAP, depth
  level depth if plan allows)      buy/sell qty                      metrics

                                   Nifty 50, Bank Nifty, sector
  Same feed, index instruments                                       context layer
                                   indices, India VIX ticks

                                                                     SMC, bar VWAP, bar
                                   1-minute OHLCV from Jan
  Historical Candle V3                                               volume profile, levels,
                                   2022 (stocks and indices)
                                                                     context, backtests

                                   instrument keys, tick size, lot
  Instrument master                                                  everything
                                   size, segment

                                   official daily OHLCV, delivery    validation, delivery
  NSE bhavcopy (public)
                                   %                                 features


Facts: feed authorize returns a websocket URL; messages are protobuf (use the official SDK
classes or the official .proto fetched in setup). Tokens expire daily ~03:30 IST. Concurrent
websocket connections per account are limited. vtt is cumulative and can reset; ltq is
only
the last trade's size; snapshots can skip trades.

Order flow has no history at Upstox. It exists only from the day recording starts, so the
recorder is the first thing deployed, and existing recordings are imported (see T05).
