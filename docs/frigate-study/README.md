# Frigate Study

A resumable system for mining [Frigate](https://github.com/blakeblackshear/frigate)'s PR
history (4058 merged PRs as of 2026-06-16) for things Nurby should learn, fix, or build.

## Goal

For every substantive Frigate PR, decide: does Nurby have an equivalent? If not, is it a
gap worth closing? Produce a prioritized, evidence-backed backlog. Prove coverage of the
whole PR history without spending equal effort on noise (dependency bumps, translations, docs).

## The pipeline

1. **Harvest** — pull merged-PR metadata in bulk into `ledger.jsonl` (number, title, merged
   date, changed file paths, body excerpt). Cheap, runs once per batch.
   ```
   gh pr list --repo blakeblackshear/frigate --state merged --limit 100 \
     --json number,title,mergedAt,files,body
   ```
   Frigate barely labels PRs, so classification keys off **changed file paths** and **title**,
   not labels.

2. **Triage** — bucket each PR by Frigate subsystem (`area`, from file paths via
   `taxonomy.md`) and `type` (feature / accuracy / performance / reliability / security /
   bugfix / refactor / deps / docs / i18n / ci / hass). Noise types are logged with
   `decision: "skip"` so coverage is provable, but not deep-mapped.

3. **Map** — for each substantive PR, write a finding: the underlying problem/insight, the
   Nurby equivalent (with file evidence), a gap class, and a proposed action. Curated
   findings go in `findings.md`; the raw row goes in `ledger.jsonl`.

4. **Synthesize** — roll findings into themed initiatives in `initiatives/` (e.g.
   hardware-accel, tracker-quality, ffmpeg-hardening) with a prioritized backlog.

## Resuming (how any session continues this)

1. Read `state.json` → `cursor_pr` is the lowest PR number already processed.
2. Harvest the next batch *older* than `cursor_pr` (we go newest → oldest).
3. Triage + map them, append to `ledger.jsonl`, add findings to `findings.md`.
4. Update `state.json` (new `cursor_pr`, counts, `updated`).
5. Re-synthesize affected `initiatives/` docs.

One PR is processed exactly once: a number present in `ledger.jsonl` is done.

## Gap classes

- **HAVE** — Nurby already has an equivalent. Record it (proves we checked).
- **PARTIAL** — Nurby has some of it; note what's missing.
- **MISSING** — real gap. Becomes a backlog item with priority + effort.
- **N/A** — not applicable to Nurby (e.g. Home Assistant integration, Coral-only paths we
  don't target). Record the reason.

## Priority / effort

Priority: **P0** security or data loss · **P1** core accuracy/perf/reliability · **P2** feature
parity · **P3** nice-to-have. Effort: **S** <1d · **M** ~days · **L** ~1wk · **XL** >1wk.
