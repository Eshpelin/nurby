# Voice phase 0. Findings

Issue #153. Status: **tooling complete, hardware answer outstanding.**

## What this phase was supposed to produce

Which transport the household's actual cameras support, with evidence, so
#155 knows what to build. That question is not answered yet, and this
document says so rather than implying otherwise.

## What was run

`scripts/probe_speakers.py` against the configured camera set:

```
CAMERA                   VENDOR     TRANSPORT            CAN  DETAIL
Tapo                     tapo       none                 no   TimeoutError:
0 of 1 camera(s) can be spoken through
```

The one configured camera is a TP-Link Tapo at `192.168.10.126:554`. It
did not answer on port 554 from this machine, and nothing else responded
on 80, 443, 2020 or 8000 either. So this is **"we could not reach it"**,
not "it cannot speak". The probe correctly reports the difference, which
is the distinction the whole `SpeakerCapability` table exists to keep.

## What is known without the hardware

**Tapo will not use the ONVIF backchannel.** TP-Link's cameras speak
ONVIF for video discovery and RTSP streaming, but their two-way audio
runs over a proprietary authenticated HTTPS API rather than the standard
backchannel. So even once the camera is reachable, the expected probe
result is "ONVIF backchannel: no", and the useful path for this
particular camera is either a Tapo-specific driver or an external speaker
through the existing `Device` row.

That is worth knowing now, because it means **the first household camera
is not going to validate the standard path.** If the intent is to ship
the vendor-neutral transport first, that needs a camera that actually
implements it: Hikvision, Dahua, Axis and Reolink all do, and any of them
would answer the question.

## The highest-risk assumption in the code

The backchannel is identified by an SDP audio section marked
`a=sendonly`. SDP direction attributes in an RTSP server's answer are
written from the **client's** point of view, so:

- `a=recvonly` audio is the camera's **microphone** (we receive)
- `a=sendonly` audio is the **speaker** channel (we send)

This reads backwards if you assume the server is describing itself, and
getting it wrong would select the microphone track and push speech into
something that never plays it, failing silently. The parser recognises
both explicitly and only accepts `sendonly`.

This follows the ONVIF streaming spec and is tested against recorded SDP,
**but it has not been confirmed against a real device.** It is the single
assumption most worth checking first when hardware is available, because
everything in #155 sits on top of it.

## What shipped

- `SpeakerCapability` table. One row per camera, written whether the
  probe succeeds or fails, with the raw RTSP head and SDP kept in
  `detail` so a later look does not need the hardware again.
- `services/voice/probe.py`. Pure parsing (SDP, RTSP status, vendor
  fingerprints, codec preference) plus a minimal DESCRIBE client.
- `scripts/probe_speakers.py`. Read-only by default; `--save` records.
- 26 tests against recorded responses from a Hikvision-shaped SDP.

Deliberately kept separate: the probe checks whether a backchannel is
*advertised*. It does not SETUP, RECORD, or push a byte of audio. Proving
a camera actually plays what we send is #155's job, and doing it here
would have meant building half the transport inside a spike.

## To finish this phase

1. Put the Tapo (or any camera) on a network this machine can reach.
2. `python scripts/probe_speakers.py --save`
3. Confirm the sendonly reading against whatever answers, ideally on a
   camera that implements the standard backchannel.
4. Update this document with the real table.

Until then, #155 should either wait or target the external-speaker
`Device` path, which needs no camera cooperation and works today.
