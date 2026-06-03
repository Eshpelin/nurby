# Onboarding self-review

A pass over the first-run flow looking for caveats, edge cases, and reuse
opportunities. Items marked DONE were fixed in the same pass.

## Correctness / lockout bugs

1. **Provisional owner could log themselves out forever.** DONE.
   A provisional account has random, unusable credentials. The navbar
   showed a plain Logout. clicking it cleared the token, and the next
   visit saw `users > 0` so `bootstrap` would not re-fire, leaving the
   user at `/login` with no password that works. Fix. hide Logout while
   provisional and surface only the Secure-account path.

2. **Concurrent first-run requests could create two owners.** DONE.
   `bootstrap` did check-count-then-insert with no lock. Two tabs or a
   double-fired effect could both pass the `count == 0` check. Fix. take a
   transaction-scoped Postgres advisory lock so bootstraps serialize. the
   second sees `count > 0` and returns 409.

3. **`/setup` was a dead end on an existing install.** DONE.
   Visiting `/setup` after setup completed posted `/auth/setup`, got 409,
   and stranded the user on a doomed form. Fix. the page now checks
   `needs-setup` on mount and redirects home when setup is already done.

4. **Demo camera duplicated on repeat.** DONE.
   `POST /cameras/demo` always inserted. Running magic twice, or clicking
   the dashboard demo button again, produced multiple "Demo Camera" rows.
   Fix. return the existing demo camera (matched by stream URL) instead.

5. **Magic could run twice (React strict mode / remount).** DONE.
   The provisioning effect had no idempotency guard, so a remount could
   fire two demo-camera POSTs and two deploys. Fix. a ref guard runs the
   sequence once per mount lifetime.

## Found in deep audit (parallel review agents)

8. **The demo camera tile rendered black.** DONE, highest impact.
   The dashboard builds a WebRTC iframe URL from the stream filename for
   every camera. But file-type streams are never published into MediaMTX
   (ingestion pulls them direct for perception only), so the path does not
   exist and the tile shows black. The demo, whose whole job is to show
   footage, would have looked broken. Fix. a remote http(s) file camera now
   renders a looping muted `<video>` the browser plays directly. footage
   appears in ~1-2s, independent of the ingestion poll-and-connect cycle.
   (frontend/src/app/page.tsx camera tile, both list and card layouts.)

9. **Claim/setup accepted malformed emails → permanent lockout.** DONE.
   `AccountClaim` and `AdminSetup` only checked `min_length`, so a value
   like "abc" could be stored as the login email. The owner could then
   never type a matching string at `/login`. Fix. server-side email-shape
   validation on both schemas.

## Robustness already handled (verified, no change)

- Magic VLM step is best-effort. no reachable Ollama is marked "skipped"
  and never blocks the dashboard, since detection, faces and rules need no
  VLM.
- Magic bails to the manual flow if the demo camera (the one hard
  requirement) cannot be created, rather than landing on an empty page.
- `bootstrap` returns 409 when an account already exists, and `auth.tsx`
  falls back to `/login` cleanly.
- The HTTP-pull deploy path registers the provider at the reachable URL,
  so the bundled Ollama service works without a host binary.

## Polish

6. **Escape to dismiss the wizard.** DONE. except during magic, where
   work is in flight.
7. **Dead `submitting` prop** on `ProviderStep`. DONE. removed.

## Decision. local AI stays opt-in, made frictionless

The choice was. ship the bundled Ollama in the default compose profile
(heavy, a ~1.5 GB image pull on every `up`) or keep it opt-in and make
enabling it trivial. Kept it opt-in. Forcing a multi-GB image on every
deployment, including CI, ARM SBCs, and users who only want local YOLO
detection, is the wrong default for a self-hostable product. Instead.
- A dashboard `LocalAIHintCard` appears when no provider is configured,
  with the one enable command and a copy button.
- The README documents `docker compose --profile local-ai up -d ollama`
  as the recommended full-experience start.
- Magic already auto-deploys a model when an Ollama is reachable, so once
  the profile is up, first-timers get a VLM with no further steps.

## Known tradeoffs (intentional, documented)

- First visitor on the network becomes the provisional owner. This is the
  cost of "no signup wall." mitigated by the loud Secure-account prompt.
  An operator who wants a hard wall can still use `/setup` first.
- Magic only pulls a model when an Ollama is already reachable. On a
  stock Docker `up` with the `local-ai` profile not started, magic adds
  the camera and honestly skips the model.
- The deploy progress creep (42 to 88 percent) is cosmetic. the pull is a
  single long call with no server-side increments. the checkmarks are
  real.
