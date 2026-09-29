# Remote access over Tailscale or WireGuard

This is the supported phase-1.5 path for technically capable households that
already operate a private mesh. It does not replace the planned HTTPS domain
ingress or the future CGNAT wizard; it provides a safe remote path today
without publishing Nurby's internal services to the LAN or internet.

## Recommended topology

Install Tailscale or WireGuard on the host running Nurby and on the phone or
computer that will use it. Reach the Nurby frontend/API through the host's
mesh address, for example:

```text
http://100.x.y.z:4748
```

Use the same mesh hostname or address as the configured public/server
endpoint in pairing settings. New pairing QR payloads can carry both the
local URL and the configured endpoint; mobile tries the local endpoint first
and falls back to the second endpoint when it is unavailable.

## Ports and media

The web and mobile clients use Nurby's authenticated, camera-scoped media
proxies:

- WHEP signaling: `/api/cameras/{camera_id}/whep`
- HLS playlists and segments: `/api/cameras/{camera_id}/hls/{resource}`

Do not expose MediaMTX's RTSP, HLS, WHEP, or API ports directly to the mesh.
The proxy re-checks camera authorization for signaling, session lifecycle,
playlists, and segments. ICE UDP remains loopback-bound by default; a
deployment that deliberately enables remote WebRTC must configure and protect
its TURN/ICE boundary explicitly. HLS is the expected fallback when direct
WebRTC media cannot traverse the mesh.

## Security checklist

1. Keep the Nurby admin account protected by a strong, unique password.
2. Restrict the mesh ACL to the household devices that need camera access.
3. Keep Postgres, Redis, Ollama, grounding, and MediaMTX management ports
   loopback-bound; mesh access should enter through Nurby only.
4. Do not use this HTTP mesh URL as an internet-facing public URL or for
   anonymous share links. Public exposure still requires the HTTPS ingress
   work tracked in #183.
5. Test from the phone with Wi-Fi disabled, then verify login, camera scope,
   live playback, HLS fallback, an alert deep link, and an exact recording
   clip before relying on the setup.

## Current limitations

- Nurby does not provision or manage Tailscale/WireGuard accounts, keys, or
  ACLs.
- The remote-access wizard, automatic TLS/domain provisioning, cellular
  reachability doctor, and CGNAT tunnel flow are not implemented yet.
- A mesh address is a private transport endpoint, not proof that the server
  is reachable from arbitrary internet networks.
