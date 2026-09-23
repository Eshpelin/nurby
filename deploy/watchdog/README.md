# Nurby external watchdog (dead-man's switch)

Nurby's own alerts (Telegram, email, push) all send **from the Nurby box**.
If that box loses power, drops off the network, or Docker stops, no alert
can go out, and the silence looks exactly like a quiet home. This watchdog
closes that gap: it runs **somewhere else** and tells you when Nurby goes
quiet through a channel that does not depend on the Nurby host.

See the full write-up (including the honest detection-window math) in
[`docs/operations/dead-mans-switch.md`](../../docs/operations/dead-mans-switch.md).

## What it watches

It polls Nurby's beacon: `GET /api/beacon` (unauthenticated, coarse
booleans only).

| Beacon result | Meaning | Watchdog acts? |
|---|---|---|
| `200` | DB + ingestion + perception + producing pipeline all confirmed | no |
| `503` | Nurby answered but monitoring is degraded (e.g. perception died) | **yes** |
| no answer / timeout | host off, unreachable, or Docker down | **yes** |

That covers partial degradation (perception dead while the API is up) as
well as a fully-dark host.

## Pick a recipe

All three run `nurby_watchdog.py`, which is stdlib-only (Python 3.9+, no
`pip install`). **Run it off the Nurby host.**

- **`github-actions.example.yml`** - hosted cron on GitHub's infrastructure.
  Zero machines to own. ~5-15 min detection window.
- **`crontab.example`** - a plain cron line for a second machine you
  control. Tightest window.
- **`docker-compose.watchdog.yml`** - a looping container for a second
  machine that already runs Docker.

## Quick test

```bash
# Against a healthy Nurby:
NURBY_BEACON_URL="https://your-nurby.example.com/api/beacon" \
  python3 nurby_watchdog.py   # prints "[watchdog] ok: HTTP 200: ..." and exits 0

# Simulate an outage (nothing listening):
NURBY_BEACON_URL="http://127.0.0.1:9/api/beacon" NURBY_FAIL_THRESHOLD=1 \
TELEGRAM_BOT_TOKEN="..." TELEGRAM_CHAT_ID="..." \
  python3 nurby_watchdog.py   # sends the alert and exits 1
```

## Configuration

See the docstring at the top of `nurby_watchdog.py` for every environment
variable. At minimum set `NURBY_BEACON_URL` and one alert channel
(`TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID`, or the `SMTP_*`/`ALERT_EMAIL_*`
set). The state file makes it alert only on the down and recovery
transitions instead of on every poll.
