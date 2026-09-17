# Audio detection: what it is and what it is not

Nurby can listen to a camera's audio track and flag a handful of sounds: baby
cry, glass break, and smoke, CO, or fire alarms and sirens. Speech phrases like
"help" are matched separately by on-device transcription. These are genuinely
useful signals, but they are informational and best-effort. This page explains
how they work and, just as important, what they cannot promise.

## How it works

Audio tagging runs locally on each camera's audio stream using a PANNs (CNN14)
audio classifier. When the model's confidence for a sound crosses the threshold
you set on a rule, Nurby emits an event that can drive alerts or device actions.
Detection needs an RTSP stream that actually publishes audio, and everything
happens on your own hardware. No audio is sent to a third party for
classification.

## Limits

- **False negatives are possible.** The model can miss a real alarm or cry,
  especially with background noise, a quiet or distant source, or a muffled mic.
- **False positives are possible.** Similar-sounding audio can trip a detection.
- **Placement and levels matter.** Mic position, gain, and the camera's distance
  from the sound source all change what gets detected.
- **Nothing here is certified.** These detectors are not UL-listed or otherwise
  certified life-safety equipment.
- **Nobody is watching for you.** Nurby is self-hosted software. There is no
  24/7 monitoring center and no human on the other end of an alert.

## Not a life-safety system

**Nurby is not a substitute for certified smoke and CO detectors, an infant or
medical monitoring device, or a professionally monitored alarm service.** Treat
audio detections as an extra, best-effort heads-up on top of the real safety
equipment you already have, never as a replacement for it. Keep certified
detectors installed and maintained, and do not rely on Nurby to protect life or
property.

## Related surfaces

The same framing appears in-product so it is not buried here:

- Rule starter templates for baby cry and help phrases carry a one-line
  disclaimer on the card (`frontend/src/lib/rule-templates.ts`).
- The rule builder's audio trigger repeats the best-effort caveat next to the
  sound-type picker (`frontend/src/components/rules/TriggerSection.tsx`).
- The per-camera **Audio & transcripts** settings page shows a disclaimer banner
  (`frontend/src/app/cameras/[id]/audio/page.tsx`).
