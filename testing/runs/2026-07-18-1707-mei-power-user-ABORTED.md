# Mei, power user — run aborted before persona session

2026-07-18, ~15:30-17:07 local (+06).

## What happened

1. Preflight clean: main up to date, stack booted fine (`start_stack.sh`),
   frontend already running on :3210 (owned by a concurrent chat session
   on this same machine — the harness note at session start flagged this).
2. Worked the open backlog first, per protocol: F76 (dashboard wall
   toolbar dead-click). Confirmed it was real, wrote a one-line fix
   (`lg:overflow-y-auto` on the left dashboard column), verified in the
   browser as Mei (fresh login, `elementFromPoint` on the "+ Camera"
   button returned the button itself, click opened the Add Camera
   modal), `tsc --noEmit` clean, committed.
3. On push, discovered another concurrent session had independently
   landed a broader fix for the same root cause (PR #124/#125, commits
   0432757 + c88c8bc) plus an unrelated copy fix (51d156a). Rebased
   cleanly, resolved one trivial one-line conflict (their version is
   strictly better — adds `scrollbar-thin` and a shell-level scroll fix
   my narrower patch didn't cover), re-verified `tsc --noEmit`, pushed.
   Corrected the FINDINGS.md F76 entry to credit the right commits.
4. Attempted to start Mei's persona session. From this point, the
   Browser pane became unreliable: pages stuck on the loading spinner
   indefinitely, `navigate` timed out at 30s, `computer` (scroll,
   screenshot) timed out at 30s repeatedly, and a direct in-page
   `fetch()` to the API origin returned "Failed to fetch" in one tab.
   Reproduced across five separate tabs/approaches (reused tab, fresh
   `tabs_create`, `preview_start` with a URL, clearing localStorage,
   navigating to different routes) with no product-side error in
   console or network logs to explain it — the API itself answered
   `curl` instantly (5ms) the whole time.
5. Checked host load directly: `uptime` reported load averages of
   237/172/137 (`top` separately showed 253/152/126 moments earlier),
   with multiple concurrent Claude Desktop renderer processes and two
   separate `claude` CLI processes visible in `ps aux` (this session
   plus at least one other, matching the harness's "another chat's dev
   server is running" note). That is host-level resource contention
   across concurrent sessions on one machine, not a Nurby defect — the
   backend, DB, and dev server all responded normally to direct
   requests throughout.

## Decision

Not filing this as a product finding: nothing here points at the app.
Not advancing `state.json`'s cursor — Mei's session never started, so
the next run should retry her fresh rather than skip to
`daniel-new-dad`. Backlog fix (F76) and the findings-ledger correction
are already committed and pushed; nothing half-applied was left behind.

## Verdict

No persona verdict this run — Mei never got past login. Environment
verdict: this host was overloaded by concurrent sessions to the point
the Browser pane tooling itself was not usable for a sustained UI test;
worth the next run checking `uptime` early and, if still this heavy,
preferring shorter/fewer interactions or waiting before diving into a
long persona flow.
