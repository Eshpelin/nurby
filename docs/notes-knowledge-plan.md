# Notes as Knowledge — Obsidian-style notes for Nurby

Status: proposal / plan. Author: design study, 2026-08-03.

## Goal

Let users keep **notes** on recordings, events, cameras, people, vehicles, zones,
and standalone topics, and make those notes **first-class context the LLM/agent
reads**. Today notes are dumb annotations on one entity type and are never fed to
the model. The Obsidian idea = notes become a small **knowledge graph** (linked,
tagged, embedded, retrievable) that the agent consults before answering.

## What exists today

- `EventNote` (`shared/models.py:1415`) — free text, **Events only**, `source`
  telegram/web/api, hard delete. Routes: `POST/DELETE /api/events/{id}/notes`
  (`services/api/routes/events.py`). **Never read by the agent.**
- `mentions.py` route — `@`-autocomplete across cameras, persons, telegram
  channels, devices. This is the seed for `[[wikilinks]]`.
- Agent = 24 read tools in `services/agent/tools.py` (`TOOL_REGISTRY`, line 2650).
  None touch notes.
- Text embeddings already in the stack: `Vector(384)`, `generate_embedding()` in
  `services/search/embeddings.py`, used by Observation/Transcript/Summary/etc.
  pgvector cosine search is a solved pattern here.

Gap: no general note object, no cross-entity attach, no linking/backlinks, no
tags, no embedding of notes, no retrieval into agent context.

## Design

### 1. Data model — one polymorphic `Note` table

Replace the event-only `EventNote` with a general `Note` (keep `EventNote`
readable during migration, or backfill + drop — see Migration).

```
Note
  id            uuid pk
  author_user_id uuid fk users (SET NULL)
  title         text null            # optional; standalone notes want one
  body          text not null        # markdown, supports [[links]] and #tags
  tags          text[] default '{}'  # parsed from #tags + explicit
  pinned        bool default false
  source        text                 # web | telegram | api | agent
  embedding     Vector(384) null     # of title+body, for RAG
  created_at / updated_at
  deleted_at    timestamptz null     # soft delete (Obsidian never hard-loses notes)
```

Attachment is many-to-many via a link table so one note can annotate several
things (e.g. "the guy in this event is the same as [[Person:Dave]]"):

```
NoteLink
  id        uuid pk
  note_id   uuid fk notes (CASCADE)
  target_kind  text   # event | recording | camera | person | vehicle | zone
                      # | incident | journey | observation | note   <- note=wikilink
  target_id uuid
  relation  text default 'attached'   # attached | mentions | about
  unique(note_id, target_kind, target_id, relation)
```

`target_kind='note'` gives **note-to-note wikilinks**; the reverse query is the
**backlinks** panel. Reuse the `mentions.py` kind vocabulary so `[[...]]` in the
editor resolves against the same entity list.

### 2. Linking / mentions

- In the editor, `[[` triggers the existing mention autocomplete (extend
  `mentions.py` to also return notes, zones, vehicles, events).
- On save, parse `[[kind:id]]` / `[[Title]]` and `#tags` out of the body →
  materialize `NoteLink` rows + `tags[]`. Unresolved `[[Title]]` = a stub link
  (Obsidian's "unlinked" behavior) that resolves once a note with that title
  exists.
- Backlinks = `SELECT ... FROM note_links WHERE target_kind='note' AND
  target_id=:id`. Show on every note and on every entity detail page
  ("Notes about this camera").

### 3. Embedding + retrieval (the part that makes the LLM "use" notes)

- On create/update, embed `title + body` with `generate_embedding()` → `Note.embedding`.
  Do it in a small worker/queue like the existing enrichment paths, not inline in
  the request, so a slow provider never blocks save.
- **New agent tool** `search_notes(query, target_kind?, target_id?, tags?, limit)`
  in `TOOL_REGISTRY`: pgvector cosine over `Note.embedding` + optional keyword
  `ILIKE` fallback (mirror `query_observations`). Returns title, snippet, links,
  updated_at.
- **Auto-injection**: when the agent is answering *about a specific entity*
  (person/camera/event in scope), fetch that entity's attached notes directly by
  `NoteLink` and prepend them to context — no tool round-trip needed. Pinned notes
  first. Budget with the existing `services/agent/budget.py` token accounting.
- This is straight RAG on top of infra that already exists; the only new storage
  is one `Vector(384)` column.

### 4. API

```
GET    /api/notes                 ?q= &tag= &kind= &target_id= &pinned=
POST   /api/notes                 {title?, body, links[], pinned?}
GET    /api/notes/{id}            includes resolved links + backlinks
PATCH  /api/notes/{id}
DELETE /api/notes/{id}            soft delete
GET    /api/{entity}/{id}/notes   convenience: notes attached to an entity
GET    /api/notes/{id}/backlinks
```

Keep the old `POST/DELETE /api/events/{id}/notes` as thin shims that create a
`Note` + `NoteLink(target_kind='event')` so Telegram-reply notes keep working.

### 5. Frontend (later phase)

- Note editor with `[[`/`#` autocomplete, markdown preview.
- "Notes" tab on entity detail pages (camera, person, event, recording).
- Backlinks panel. Optional graph view is a stretch goal, not core value.

## Phasing

- **P1 — model + API.** `Note` + `NoteLink` tables, migration off `EventNote`,
  CRUD routes, event shims. No AI yet. Ship value: cross-entity notes + backlinks.
- **P2 — embedding + agent tool.** Embed on save, `search_notes` tool, auto-inject
  attached notes into agent context. This is the "LLM uses your notes" milestone.
- **P3 — editor + backlinks UI.** `[[`/`#` autocomplete reusing `mentions.py`,
  notes tabs on entity pages.
- **P4 — polish.** Graph view, note templates ("incident report", "camera SOP"),
  daily-journal note, note → rule ("alert me when this note's subject appears").

## Migration

`EventNote` → `Note` + `NoteLink`:
1. Add new tables (alembic).
2. Backfill: each `EventNote` row → one `Note` (source, text→body, author,
   created_at) + one `NoteLink(target_kind='event', target_id=event_id)`.
3. Switch event routes to shims.
4. Drop `event_notes` in a later migration once shims are proven.

## Open questions

- Access control: notes inherit the target entity's ACL
  (`UserCameraAccess`/`ResourceShare`), or are they per-author private with opt-in
  share? Recommend: inherit target ACL; standalone notes are author-private + share
  via existing `ResourceShare`.
- Do agent-written notes (`source='agent'`) get flagged in UI so users can trust
  provenance? Recommend yes.
- Should note embeddings also feed global `/api/search`? Cheap win in P2.
