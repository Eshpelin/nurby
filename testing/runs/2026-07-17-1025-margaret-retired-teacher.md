# Run: margaret-retired-teacher — 2026-07-17

Second ux-army run. Margaret, 68, retired teacher. Tech: low. Reads
every word, afraid of breaking things, never edits a URL, jargon stops
her cold. Two failed attempts on the same thing = she gives up.
Situation: lives alone; daughter mounted one camera over the front door
and left.

First run to use the pre-seeded persona logins (margaret@ux-army.test).
Logging in was a non-event, which is the point — no invite-key hunt, no
login wall.

## Goals attempted

- Finish setting up "whatever this asks me to do" — DONE (1/4 → camera added)
- Know when someone comes to the door — NOW POSSIBLE (was impossible before this run)
- See who came by yesterday — partially; no history yet, but today's door activity is visible
- Find the "call for help" type features, if any — NOT REACHED (budget)

## Narrative

Logged in cleanly. Dashboard greeted her with "Finish setting up Nurby
0/4", which is exactly the thing her persona wants: a list of what to
do. Good.

She clicked the first item, "Demo camera only. Add your own camera".
The Add Camera modal opened, and the very first thing she read was a
Name field showing **Front Door** — precisely the name she wanted —
above a greyed-out button reading "Enter a Name above to continue."
It's a placeholder, not a value (confirmed: `value === ""`). For a user
who reads every word and trusts what's on screen, that's a direct
contradiction: the field says Front Door, the button says enter a name.
Logged as **F70**. Compare Stream URL, whose placeholder
(`rtsp://192.168.1.100:554/stream1`) is unmistakably an example — the
Name field should read the same way.

She typed the name, then hit the real wall: Stream URL. "RTSP", "HTTP
MJPEG", "HLS", "ONVIF" — pure jargon, exactly what stops her. But the
UI does the right thing here and offers "Don't know your camera's URL?
Pick your brand", which is aimed squarely at her. She clicked it and
got ~25 brands in a grid: Hikvision, Dahua, Reolink, Ubiquiti, Hanwha
Vision / Wisenet (Samsung), Avigilon (Motorola)... with no search box
and no "I don't know" option. Margaret didn't install this camera — her
daughter did — so she doesn't know the brand, and the one affordance
built for her dead-ends. Logged as **F71**. Worth noting the product
already has the right answer for this (the Scan Network tab), but the
brand list never points at it.

In character she fell back to the URL her daughter left on a note, and
the camera was created — no error, modal closed, checklist ticked to
1/4 with a ✓. That part was smooth.

Then the run hit the real problem. The camera sat at **offline**
forever, the dashboard said "Nothing happened yet" and "Some cameras
are offline. Check their stream URLs or credentials." The RTSP feed was
definitely publishing (ffmpeg running against
rtsp://localhost:8554/front-door). Cause: `ingestion` and `perception`
are defined in docker-compose but the harness **never started them** —
start_stack.sh only brought up postgres, redis, mediamtx and the API.
Nothing was consuming any camera, on any run, for any persona. Every
persona's central goal — did someone come to the door, did my rule
fire, who was here yesterday — has been silently untestable this whole
time. Logged and fixed as **F68**.

The compose services couldn't be reused as-is: they hardcode the
`nurby` database and reach peers by service name (postgres:5432,
rtsp://mediamtx:8554), and `rtsp://localhost:8554/...` — the URL a
persona actually types — doesn't resolve from inside a container. So
both now run on the host from .venv-test, exactly like the API already
does, pointed at the uxtest DB and scratch media paths.

While verifying that, perception started logging keyframes for cameras
named `Living Room` and `Backyard` — rows that exist only in the main
`nurby` dev database, not in nurby_uxtest. Motion keyframes travel over
the Redis stream `nurby:motion`, both stacks defaulted to Redis db 0,
and streams persist — so uxtest perception was replaying the dev
stack's leftover backlog into the uxtest database. Logged and fixed as
**F69** by pinning the uxtest stack to redis db 1.

With both fixed, Margaret's dashboard came alive for the first time:
Front Door showing **REC** at 1280x720/15fps, the digest reading
"Activity was recorded on Demo Camera, Front Door. Detections included
car, person, bicycle", and the timeline showing **"Person seen 1×" on
Front Door**. Her core question — did someone come to my door — is
answerable now, with no AI provider configured, which is exactly what
the "detection works without AI" banner promises.

## Findings

- F68 (blocker, fixed): harness never started ingestion/perception →
  no camera ever online, zero detections, core product untestable for
  every persona.
- F69 (major, fixed): uxtest stack shared Redis db 0 with the main dev
  stack → perception replayed foreign keyframes into the uxtest DB.
- F70 (minor, open): Add Camera's Name placeholder "Front Door" reads
  as a filled value while the disabled button demands a name.
- F71 (polish, open): brand picker is an unsearchable ~25-item grid
  with no "I don't know" escape, and never points at Scan Network.

## What worked

- Pre-seeded login: straight in, no wall. The fix from the last session
  did its job.
- The setup checklist is the right shape for a low-tech user: a short
  numbered list of what's left, and it ticked to 1/4 with a ✓ the
  moment the camera was added.
- Camera creation itself: no errors, modal closed cleanly, feed picked
  up within ~10s once ingestion existed.
- Detection genuinely works with no AI provider configured, as
  advertised.

## Harness/tooling note (not a product finding)

`resize_window` breaks the Browser pane's click coordinate mapping —
after any resize, clicks land at a multiplied offset (measured 8x at
1280x800, ~5.2x at the tablet preset) and silently hit the wrong
element or nothing. Only the pane's native size (320x317 CSS px, screenshot
640x634 → coords = screenshot/2) maps correctly. This cost a chunk of
this run's budget and nearly produced a bogus "checklist item does
nothing" finding. **Future runs: do not resize; work at native size and
prefer ref-based clicks.** The 320px-wide pane means personas are
effectively testing the mobile layout — worth knowing when judging
"cramped" as a finding.

## Margaret's verdict

"It told me exactly what to do next, which I appreciated. But it asked
me for a name when the box already said Front Door, and then it wanted
an address for the camera that I've never seen in my life — my daughter
put it up. When I finally got it in, it did show me that someone came
to the door, and that's really all I wanted."
