# Operating the bot

Always run commands from the repo root, with the same config. Live trading is not available.

## Start
```bash
sentinel-quant data download     # once, then when you want fresher history
sentinel-quant gui               # http://127.0.0.1:8765, use Start service there
```
Or run `sentinel-quant run` directly. Only one service can run per mode.

## Modes
- `sim` (default): simulated fills on real mainnet candles. No keys.
- `paper`: Binance spot testnet. Run with `--config configs/paper.yaml`, plus `SQ_EXCHANGE_API_KEY` and `SQ_EXCHANGE_API_SECRET` in `.env`, using **testnet keys only**. Its files live in `runs/paper`, so it can run beside `sim`. Open its panel with `gui --config configs/paper.yaml --port 8766`. The kill switch is shared: one switch stops both.

## Emergency stop
```bash
sentinel-quant kill-switch on
```
Every order is refused, exits included. Stops already resting at the exchange stay in place. The service keeps running. Release with `kill-switch off` or from the panel.

## If reconciliation fails
The kill switch engages by itself and a critical alert is sent. Do not release it until you know why. Compare `reconciliation_failed` in the decision log with the account.

## After a crash
Start again. The service restores its risk state, re-sends unfinished orders under the same ids, and catches up on missed bars without trading them.

## Where things are
`runs/ledger-<mode>.sqlite` (orders, fills, decisions), `runs/reports/` (daily reports), `runs/logs/`, `runs/registry.sqlite` (backtests). To start a fresh simulation, stop the service and delete `runs/ledger-sim.sqlite`.

## Validating a strategy
`sentinel-quant validate` runs gates G2 to G6 on data before `validation.holdout_start`. It runs many variants, and each one counts as a trial.

`validate --open-holdout` spends the holdout for G3. Do this once, and only for a strategy you have finished changing: any later run on that data is no longer out of sample, and the report will say so.

## Telegram alerts
Set `alerts.telegram_enabled: true`, plus `SQ_TELEGRAM_BOT_TOKEN` and `SQ_TELEGRAM_CHAT_ID`.
