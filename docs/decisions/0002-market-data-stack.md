# ADR 0002 — Market data stack and dataset versioning

- Status: accepted
- Date: 2026-11-06

## Context
MVP-2 needs crypto spot history and live closed candles for research and the paper bot. A backtest is only reproducible if it names exact data, and a strategy must never act on a bar that is still forming.

## Decision

### Dependencies
- **ccxt** (`>=4.5,<5`) for exchange access: official public REST APIs behind one interface, so later exchanges need no new client.
- **polars** (`>=2.1,<3`) for frames, Parquet read and write.
- **pyarrow** (`>=26`) for reading Parquet footers during verification, as an implementation independent of the polars writer, and for later interchange (DuckDB).
- Bounds are capped at the next major because a data library change must be a deliberate upgrade. Each manifest records the ccxt version.

### Source: public mainnet, no credentials
`exchange.testnet` governs order routing only. Testnet is not real market activity, so it is no basis for research; market data always comes from public mainnet. The client is built without keys and has no order methods, so this step cannot touch an account. Market loading is limited to spot.

### "Closed" has one definition
A bar opening at `t` is closed when `t + timeframe <= exchange_now - close_grace_seconds` (`closed_cutoff_ms`). Exchange time is used, not the local clock, because a fast local clock would otherwise release a forming bar. The grace period allows for trades still landing at the boundary. History download and live polling share this function.

### Bars are stored as received
The pipeline never sorts, deduplicates or repairs. Repairing would hide the problems the quality report exists to find. Bad data is stored for diagnosis, marked `fail`, and `DatasetStore.load` refuses it unless the caller uses `read_verified` deliberately.

### Severity
Errors (fail): non-UTC timestamps, duplicates, out-of-order or misaligned bars, unclosed bars, null or non-positive prices, inconsistent OHLC, negative volume.
Warnings: gaps and zero-volume bars. Real exchange outages produce these, for example Binance on 2023-03-24, so failing on them would block every real dataset. `data report --strict` treats them as failures. How strategies handle gaps is a later decision.

### Versioning
- `dataset_id = <exchange>_spot_<BASE-QUOTE>_<timeframe>_<first 12 hex of content hash>`.
- `content_sha256` hashes bar values, not Parquet bytes, so the id survives a change of compression or library version. `file_sha256` separately detects corruption.
- Version directories are immutable and written by atomic rename. `latest.json` is replaced atomically. Each manifest names its parent.
- Re-runs fetch only bars missing before or after the stored range. No new bars means no new version. `--full` re-fetches the range, which is how restated history surfaces.

### Live polling
Synchronous REST polling, not websockets: at bar timeframes one request per bar close is enough, and restart catch-up is simply "resume from the last emitted bar". Delivery is at-most-once inside a process; the caller persists the last processed bar and passes it as `start_after` (MVP-6).

## Consequences
- Each version is a full copy. That is about 1 MB per symbol for 6 years of 1h bars, but frequent incremental runs at 1m would need a retention policy.
- An interrupted first download saves nothing and restarts from the beginning. Acceptable at current sizes (under a minute for two symbols).
- Incremental runs do not re-check stored bars, so restatements appear only with `--full`.
- Timeframes are limited to those aligned to the Unix epoch (`1m` to `1d`). `1w` and `1M` are rejected at config load.
- M1 still needs a second exchange, outlier checks, stocks and calendars.
