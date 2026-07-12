# Remote Access Design

Goal: a non-expert user can reach their Nurby server from anywhere (mobile app,
browser, share links) with an out-of-the-box experience. The system detects
whether it is reachable from the internet and guides the user through the one
step we cannot do for them. The maximum we ask of a user is "buy a domain and
point it at your server" — everything else (TLS, renewal, routing, fallbacks)
is automatic. Exposure must not weaken the privacy posture: remote access is
opt-in, TLS-only, rate-limited, and share links remain scoped to exactly one
resource.

## Where we are today

- The API listens on `:4748`, plain HTTP, no TLS anywhere in the stack.
- MediaMTX exposes three more ports: `:8889` (WHEP/WebRTC HTTP), `:8189/udp`
  (ICE media), `:8888` (HLS). The mobile app builds these URLs by swapping the
  port on the API host (`live_view.dart`), so remote access would require four
  ports forwarded — a non-starter for normal users.
- `public_base_url` is a string setting used to print URLs (share links,
  Telegram webhook). Nothing verifies it is actually reachable.
- The doctor checks db/redis/mediamtx/smtp/disk/cameras/providers, but has no
  concept of network reachability.
- Mobile stores a single `server_base_url`; the pairing QR embeds the LAN URL.
  Off-LAN, the app is dead.
- Share links (`/share/<token>`) are already well-scoped for anonymous access:
  hashed tokens, forced expiry, view caps, revocation, single resource, no
  live access. They are ready for public exposure; the network is not.

## Design principles

1. **One port.** Everything — frontend, API, WHEP signaling, HLS — goes
   through a single HTTPS ingress. If only one thing gets forwarded, the whole
   product works.
2. **Detect, then guide.** The system figures out the network situation
   (public IP, CGNAT, port reachability) and tells the user exactly which
   path applies to them. No generic networking documentation dumps.
3. **Remote is opt-in.** Default install stays LAN-only. Enabling remote
   access is an explicit wizard with an explicit security gate.
4. **Fail closed.** If TLS can't be provisioned or reachability can't be
   verified, remote mode does not activate. No "works but insecure" state.
5. **Graceful media fallback.** WebRTC when the network allows it, HLS through
   the same HTTPS port when it doesn't. Remote live view must never depend on
   a UDP port being open.

## Architecture

### 1. Single ingress: bundled Caddy

Add a `caddy` service to docker-compose as the only user-facing listener
(`:80`/`:443` in remote mode; keeps `:4748` mapped for LAN back-compat):

```
/api/*    -> api:8000
/whep/*   -> mediamtx:8889   (WHEP signaling; path-rewritten)
/hls/*    -> mediamtx:8888
/*        -> frontend
/share/*  -> frontend (viewer page; its /api/share/* calls hit the api route)
```

Why Caddy: automatic Let's Encrypt issuance + renewal with zero config beyond
the domain name, automatic self-signed certs for LAN, small, single binary.

The mobile app and web frontend switch from port-swapping to relative paths
(`{base}/whep/{camera}`, `{base}/hls/{camera}`). This is required work even
for the tunnel path — any single-hostname ingress needs it.

### 2. Connectivity doctor

New doctor section + dedicated `GET /api/system/connectivity` endpoint:

| Check | How |
|---|---|
| Public IP | STUN query (also used by WebRTC anyway); fallback HTTPS IP echo |
| CGNAT detection | Compare STUN-observed public IP with router WAN IP via UPnP/IGD query. Mismatch or RFC6598 (100.64/10) address ⇒ CGNAT |
| UPnP available | IGD discovery on the LAN |
| Port reachable from outside | Ask an external vantage point to connect back (see below) |
| TLS valid | Local handshake against `public_base_url` |
| DNS correct | Resolve the user's domain, compare with detected public IP |

**External reachability probe.** A server cannot verify its own external
reachability from inside the LAN (hairpin NAT lies). Two options, in order:

1. *Phone-assisted probe (zero infrastructure, ships first).* The wizard shows
   a QR encoding `https://{domain}/api/health?probe={nonce}`. The user scans
   it with their phone **on cellular data**. The backend sees the nonce arrive
   from a non-LAN address and marks reachability confirmed. Honest, free, and
   fits the pairing-QR pattern users already know.
2. *Hosted probe (later).* A tiny stateless endpoint we run
   (`probe.nurby.app`): the server asks it to connect back to
   `{ip}:{port}` and report. Removes the manual step; adds first-party
   infrastructure we currently don't have.

### 3. Remote access wizard (Settings → Remote access)

State machine driven by the connectivity doctor:

```
disabled ──[enable]──> detecting
detecting ─┬─ public IP + port forwardable ──> domain_setup
           └─ CGNAT / no forwarding ─────────> tunnel_setup   (Phase 2)
domain_setup: enter domain → wizard shows detected public IP and
  registrar instructions ("create an A record pointing at 203.0.113.7")
  → attempt UPnP mapping for 443, else show per-router port-forward help
  → Caddy obtains Let's Encrypt cert → phone-probe QR → verified
verified: public_base_url set automatically; pairing QRs now carry both URLs
```

Security gate on "enable": require a strong admin password (reject the
seed/default password outright), enforce TLS-only, and turn on the exposure
hardening set (below). Refuse to activate remote mode over plain HTTP.

**Dynamic IP:** built-in DDNS updater. The wizard asks which DNS provider the
domain uses; for providers with an API (Cloudflare, deSEC, DuckDNS, Porkbun,
etc.) the user pastes an API token and we keep the A record updated (re-check
every 5 minutes via STUN, update on change). No supported provider ⇒
recommend a free DuckDNS subdomain as the A-record target and CNAME to it.

### 4. Mobile: dual URL + automatic failover

Home Assistant's model, proven with exactly our audience:

- `ServerConfig` grows `internalUrl` + `externalUrl` (keep the existing key as
  internal for migration).
- Connection strategy: try internal with a short timeout, fall back to
  external. Cache which one worked; re-probe on network change events
  (wifi ⇄ cellular).
- The pairing QR payload includes both URLs, so pairing on LAN once gives
  remote access with no extra typing.
- Push notifications already work off-LAN (APNs/FCM path); deep links from a
  push must open via the external URL when off wifi.

### 5. Live video from outside

WHEP signaling rides the HTTPS ingress, but WebRTC *media* is UDP and will
fail through a single forwarded TCP port unless the ICE story is solved:

- Configure MediaMTX with a public STUN server; advertise the detected public
  IP as an additional host candidate; enable ICE-TCP
  (`webrtcLocalTCPAddress`) so media can fall back to TCP through the ingress
  host when UDP `8189` is not forwarded.
- **Hard fallback: HLS through the ingress.** Works through any HTTPS path,
  including tunnels and CGNAT, at the cost of a few seconds latency. The
  mobile player tries WHEP first with a fast (≈3 s) connection deadline, then
  silently switches to HLS. Remote live view must never show a spinner
  forever because of NAT.
- Optional (later): embedded TURN relay for low-latency remote WebRTC.

Note: anonymous share links never include live video (by design), so *shares*
need none of this — only the authenticated mobile/web experience does.

### 6. Exposure hardening (activates with remote mode)

- Rate limiting at Caddy: tight buckets on `/api/auth/*` (login, pair/claim)
  and `/api/share/*`; sane global ceiling elsewhere.
- Login lockout with exponential backoff per account + per source IP.
- HSTS, secure cookie flags, HTTPS-only redirects.
- Audit log entries for remote logins with source IP + device.
- Doctor warning (red, permanent) if remote mode is on and any user has a
  weak/default password.
- docker-compose: stop publishing internal ports (postgres `5433`, redis
  `6379`, grounding `8800`, mediamtx `8554`) on `0.0.0.0` — bind them to
  `127.0.0.1` regardless of remote mode. They are LAN-exposed today for no
  end-user reason.

### CGNAT / no-port-forward users: tunnel path (Phase 2)

For users the doctor diagnoses as CGNAT'd (or who fail port forwarding), the
wizard offers a tunnel instead of a domain. Recommended: **Tailscale Funnel**
— works behind CGNAT, no router changes, no published home IP, and TLS
terminates on the user's node so the relay sees only ciphertext (fits the
privacy story; Cloudflare Tunnel does not, since Cloudflare decrypts).
Trade-offs: requires a free Tailscale account, `*.ts.net` hostname, relay
bandwidth limits. Long-term, a first-party relay (Nabu Casa model) is the
best UX and a revenue line, but it is operational commitment we should not
take on yet.

## Phasing

**Phase 1 — single ingress + domain path (the core ask)**
1. Caddy service, path routing, LAN back-compat on `:4748`.
2. Frontend + mobile switch to relative media paths (`/whep/*`, `/hls/*`).
3. Connectivity doctor (STUN public IP, CGNAT detect, UPnP, DNS check).
4. Remote access wizard with domain flow, Let's Encrypt, phone-probe QR.
5. Exposure hardening set + internal port binding cleanup.
6. Mobile dual-URL failover; pairing QR carries both URLs.
7. HLS fallback in mobile live view.

**Phase 2 — no-port-forward path**
8. Tailscale Funnel toggle for CGNAT'd users, scoped ingress
   (optionally share-paths-only mode).
9. DDNS provider integrations beyond the initial set.
10. ICE-TCP / TURN work for low-latency remote WebRTC.

**Phase 3 — zero-step (business decision)**
11. First-party relay service, on by default, E2E-encrypted.

## Decisions to confirm

1. Phone-assisted reachability probe acceptable for v1 (vs. standing up
   `probe.nurby.app` now)?
2. Caddy vs. keeping the field open for users' own reverse proxies — proposal
   is to bundle Caddy but document a "bring your own proxy" escape hatch
   (`REMOTE_MODE=external-proxy` skips cert management).
3. Does remote mode expose the full authenticated app (proposal: yes, with
   hardening) or should there also be a share-links-only exposure level?
