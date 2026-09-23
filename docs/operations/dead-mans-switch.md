# Dead-man's switch: know when Nurby itself goes dark

**Issue:** #211 · **Status:** beacon shipped, recipe shipped, productized Settings UI deferred.

## The problem

Every alert Nurby can send (Telegram, email, push) is sent **from the box
that runs Nurby**. So the one failure that matters most for the
away-from-home persona, the box losing power, dropping off the internet, or
Docker going down, is exactly the failure that makes Nurby unable to tell
you anything. From your phone, a dark Nurby and a quiet house look
identical.

A dead-man's switch fixes this by inverting who does the talking: something
**outside** Nurby checks in on Nurby, and shouts when Nurby stops answering.

## What Nurby provides: the beacon

`GET /api/beacon` (unauthenticated, coarse booleans only, no camera data).

It is deliberately stronger than `/api/health`. `/api/health` only proves
the API process can reach its database. The beacon proves the home is
actually **being monitored**, by reading the same heartbeat and
component-health keys the doctor inspects (`shared/heartbeat.py`,
`shared/component_health.py`) so there is one source of truth:

| Check | Source | Why it matters |
|---|---|---|
| `database` | `SELECT 1` | API can read its own store |
| `ingestion` | `nurby:heartbeat:ingestion` | frames are being pulled |
| `perception` | `nurby:heartbeat:perception` | frames become observations |
| `observation_writer` | `nurby:health:observation_writer` | the pipeline is producing, not silently failing every write |

Response:

```json
{
  "beacon": "alive",
  "healthy": true,
  "checks": {"api": true, "database": true, "ingestion": true,
             "perception": true, "observation_writer": true},
  "failing": [],
  "stale_after_seconds": 35,
  "generated_at": "2026-09-23T12:00:00+00:00"
}
```

- **HTTP 200** when every critical capability is confirmed.
- **HTTP 503** when Nurby answered but monitoring is degraded, e.g.
  perception died while the API stayed up. `failing` names the culprits.
- **No answer / timeout** when the host is off, unreachable, or Docker is
  down.

A status-code-only external poller (`curl -f`) therefore trips on both a
partial degradation and a full outage. The beacon **fails closed**: if it
cannot confirm a capability (Redis unreachable so a heartbeat cannot be
read, or a session cannot be opened), it reports degraded rather than
guessing healthy.

## What you run: the external watchdog

Copy-paste recipes live in [`deploy/watchdog/`](../../deploy/watchdog/):

- `github-actions.example.yml` - hosted cron, no machine to own.
- `crontab.example` - a cron line for a second machine.
- `docker-compose.watchdog.yml` - a looping container for a second machine.

All run `deploy/watchdog/nurby_watchdog.py` (stdlib only, Python 3.9+),
which alerts through an **off-box** channel (Telegram bot or hosted SMTP)
and remembers state so it pings you on the down and recovery transitions,
not on every poll.

> **The one rule that makes this work:** the watchdog and its alert channel
> must not run on the Nurby host. A watchdog on the same box dies with the
> box and tells you nothing. Put it on GitHub's cron, a VPS, or a second
> Pi on a different power strip and network.

## Being honest about the detection window

Your real "time to know" is:

```
poll_interval  +  up to stale_after_seconds (35s)  ×  fail_threshold
```

The `stale_after_seconds` term is because a worker that just died still
reads as alive until its heartbeat key expires (TTL = 35s today). So:

| Recipe | Poll interval | Threshold | Honest window |
|---|---|---|---|
| GitHub Actions | ~5 min (can be delayed) | 1 | ~5-15 min |
| cron (second machine) | 2 min | 2 | ~4-5 min |
| compose loop | 2 min | 2 | ~4-5 min |

Pick the interval that matches how quickly you need to know. Tighter is not
free: it costs more polls and more chances for a transient network blip to
page you (raise `NURBY_FAIL_THRESHOLD` to absorb blips).

## Verifying it (acceptance)

1. **Full outage:** power off (or `docker compose stop`) the Nurby host.
   Within the window above, the watchdog should send "🚨 Nurby stopped
   reporting" from the off-box channel. Bring it back: expect one
   "✅ Nurby is reporting again".
2. **Partial degradation:** with the API still up, stop only perception
   (`docker compose stop perception`). `GET /api/beacon` returns 503 with
   `"failing": ["perception"]`, and the watchdog trips the same way.

## Deferred

- A Settings screen that generates the recipe pre-filled with the user's
  public URL and channel, and nags during onboarding until an external
  watchdog has checked in at least once. Ship after the copy-paste pattern
  is validated in the field (per the issue).
- Recovery of the box itself is out of scope here; that is backup/restore
  (#189). This issue is detection only.
