# Product execution — 16 September 2026

Roadmap: https://github.com/Eshpelin/nurby/issues/200

## Backlog

| Priority | Issue | Scope |
|---|---|---|
| P0 | #190 | Explicit camera access and safe revocation |
| P0 | #191 | Guardian pickup evidence versus confirmed handover |
| P0 | #192 | Review-first consequential workplace templates |
| P0 | #201 | Remaining camera-scope enforcement across read surfaces |
| P1 | #193 | Real-alert onboarding |
| P1 | #194 | Monitoring coverage |
| P1 | #183 | Remote access — existing issue extended with cellular acceptance |
| P1 | #195 | Structured alert feedback |
| P1 | #198 | Ask evidence, searched scope and gaps |
| P1 | #199 | Audience validation and retained monitoring metrics |
| P2 | #196 | Reversible tuning based on reviewed examples |
| P2 | #197 | Incident ownership and resolution |

## First implementation batch

Branch: `codex/product-trust-foundations`.

- Camera policy has explicit `all`, `selected`, and `none` modes. An empty selection denies access. New non-admin accounts default to none; invited users receive their selected camera grants. Existing admin and unrestricted accounts become explicit all-mode users in migration; existing selected accounts remain selected.
- Admin controls on web/mobile expose the policy and effective selection. Single-camera edits cannot silently switch an all-mode account to a restricted selection. Bulk replacement validates camera IDs and deduplicates them before changing grants. Policy/grant mutations serialize on the user row.
- Dashboard sockets recheck access before delivering each batch. Deactivation or a permission-read failure suspends delivery. This adds database work proportional to connected users per batch and should be profiled on high-volume deployments; it avoids stale authorization and cross-process invalidation races.
- Guardian pickup messages now describe possible pickups and approved-entry matches, explicitly saying handover is not confirmed. The timeline renders historical pickup rows using the new wording without changing stored audit rows. Old delivered notifications are not recalled or rewritten. Staff-confirmation/correction workflows remain outstanding in #191.
- The guest-fee starter now creates a review alert, without a CRM charge action. The template warns that its sequence may represent the same person. Existing saved rules are deliberately not rewritten; operators must review any previously configured billing rule. Approval, shadow-mode and action-receipt work remains in #192.

## Migration and release notes

Apply `f9c2d4e6a8b0` before starting this application version, and deploy web/mobile clients with the updated access semantics. Invitations with no camera selections now create no-camera users; admins can explicitly grant all access later. Existing accounts retain their effective legacy scope through the backfill.

The migration intentionally refuses downgrade: the previous schema cannot represent no-camera access, so removing the mode would widen access for denied accounts. Any rollback needs a separately reviewed access-preserving plan. No migration or deployment was applied to the user's running database during this work.

The source audit discovered unscoped search, timeline and summary reads. Those existing gaps are tracked in #201. **This batch is not proof of end-to-end camera isolation and does not complete #190.** Complete that audit and media-path validation before expanding shared deployments.

## Validation

- Full backend suite: 2,258 passed, 3 skipped before the final additional all-mode transition test; the affected permission suite is rerun after that test.
- Mobile suite: 249 passed; Flutter analysis passed.
- Web suite: 32 passed plus 2 additional permission-page interaction tests passed.
- Production web build and TypeScript checking passed.
- Python CI lint rules passed.
- Migration backfill exercised with representative legacy rows; PostgreSQL DDL generated through Alembic offline mode. A live PostgreSQL upgrade and real camera/mobile end-to-end checks remain to be performed.

No issues are closed automatically by this batch. Implementation, deployment and real-world validation are distinct milestones.

## Continued implementation — 17 September 2026

All six GitHub checks passed on PR #202. The next branch, `codex/camera-read-scope`, implements scoped search/review/audio reads and background-scan revocation for #201. See [the implementation and remaining audit record](camera-read-scope-2026-09-17.md). It depends on the first branch and does not close the camera-isolation release gate.
