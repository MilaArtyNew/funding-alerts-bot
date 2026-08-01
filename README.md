# Funding Alerts Bot

Funding-rate alert bot for crypto derivatives markets. It monitors funding conditions and sends Telegram alerts when configured thresholds or opportunities appear.

## Features

- Monitors funding rates and related market conditions.
- Sends Telegram alerts for configured funding opportunities.
- Documents bot token, schedule/threshold configuration, and deployment notes.

## Architecture

- **Repository:** `MilaArtyNew/funding-alerts-bot`
- **Primary stack:** Python, systemd, Railway
- **Entrypoints and scripts:**
  - `main.py`
- **Notable dependencies:** `httpx`

## Configuration

Configure the service with environment variables. Do not commit real secrets to the repository.

- `TELEGRAM_CHAT_ID` — required or optional runtime configuration. See deployment environment for the actual value.
- `TELEGRAM_TOKEN` — required or optional runtime configuration. See deployment environment for the actual value.

## Setup

```bash
git clone https://github.com/MilaArtyNew/funding-alerts-bot
cd funding-alerts-bot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running Locally

```bash
python main.py
```

## Bot Commands

No interactive Telegram commands were detected automatically. If this service sends alerts only, document the operational controls here when they are added.

If a command requires extra input and the argument is missing, the bot should ask a follow-up question instead of failing silently.

## Deployment Notes

- Keep secrets in the deployment platform environment variables, not in Git.
- Use the default branch as the source of truth for deployments.
- Check logs after every deployment and verify the `/status` or health endpoint when available.
- If the project uses a scheduler, verify timezone assumptions and idempotency before enabling it in production.

## Operational Notes

- Review logs after startup for missing environment variables or API authentication errors.
- Keep command names in English and document every user-facing command in this README.
- For Telegram bots, `/help` should list the same commands documented here.
- Inline buttons should edit the original message with the final status rather than sending duplicate messages.

## Troubleshooting

- **Bot does not respond:** verify the bot token, webhook/polling mode, and chat permissions.
- **Missing data:** check API keys, rate limits, and upstream service status.
- **Deployment starts but exits:** inspect platform logs for missing environment variables or import errors.
- **Commands differ from README:** update the command list here and in the bot command menu at the same time.

## Security

- Never commit `.env` files, API keys, private keys, Telegram tokens, or session strings.
- Use `.env.example` for placeholders only.
- Rotate any credential that was accidentally committed.

## Deployment: VPS (since 2026-08-01)

Moved off Railway because Binance (`451`) and Bybit (`403`) geo-block Railway egress IPs,
so the long/short ratio never arrived and the verdict silently degraded.
Both sources answer normally from the VPS.

```bash
sudo systemctl status funding-alerts-bot
sudo journalctl -u funding-alerts-bot -f
```

Unit file: `systemd/funding-alerts-bot.service`, env in `.env` (chmod 600, owner `gpt`).

### DRY_RUN

`DRY_RUN=true` collects snapshots and evaluates signals but sends nothing to Telegram
and forwards nothing to the executor — the formatted message goes to the log instead.
Needed when relocating: `OI 1h/4h` require 4 hours of local snapshot history, and until
that exists every verdict would be `н/д`.
