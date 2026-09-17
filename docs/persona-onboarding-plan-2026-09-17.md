## Product outcome

Help each person reach a useful monitoring outcome, then return to a relevant daily workspace. A homeowner, shop operator, installer and invited viewer should not receive identical setup instructions. Personalization preferences must never grant permissions or silently change existing rules.

## Execution plan

### 1. First release: personal goals and recommended workflows
- Add account-owned, server-persisted onboarding preferences, separate from installation-wide dismissal flags and authorization roles.
- Offer Home and Small Business contexts to administrators, then a small set of goals: entrance activity, deliveries, after-hours activity, or reviewing footage. Allow an installation-focused preference and an explore path.
- Preview the recommended workflow in plain language, including prerequisites and what the user still needs to configure/test. Reuse the existing rule builder and templates; choosing a goal does not activate a rule.
- Show a persistent, relevant dashboard card with the next action, review shortcut and change-preferences control. Do not replace the established navigation.
- Give invited viewers a review path without camera/provider/rule installation steps. Guardians retain their authorized dependant portal.
- Avoid forcing AI-provider setup for detection-only goals. Save errors must be visible and retryable; preferences must survive sign-in on another device.

### 2. Verified first useful result (linked to #193)
- Track configured, tested and confirmed-useful separately, tied to a specific rule/camera and real event/delivery/evidence.
- Guide a physical camera test and review of the exact evidence; label synthetic tests separately.
- Resume unfinished steps across sessions and measure server-ready-to-first-useful-result separately from installation time.

### 3. Context and daily workflows
- Add explicit place/workspace context before supporting a person with multiple sites; per-account preferences in phase 1 are not a multi-tenant workspace model.
- Extend invitations with validated context and responsibilities, preserve permission boundaries, and build staff/guardian workflows after facility validation.
- Add audience-specific daily priorities, workflow pause/edit controls and capability-aware recommendations. Never rewrite saved rules when preferences change.

### 4. Validation and rollout
- Observe Home and Small Business users choosing a goal, finishing a workflow and returning after seven days.
- Measure time to first useful result, notification/evidence success, seven-day workflow use, abandonment and noisy-rule disablement by goal/responsibility.
- Test account isolation, restricted-user paths, invalid goal/context combinations, retry/reload behavior, and rule-preview behavior.

## First-release acceptance criteria

- [ ] Admins can choose Home/Small Business, one relevant goal, and daily-use/setup focus; explore remains available.
- [ ] A preview explains the recommendation and remaining configuration/testing before saving.
- [ ] Preferences persist per user across devices; users cannot write another account's preferences or authorization fields.
- [ ] Invited viewers receive a review-only path; guardians retain their portal; installation controls are not recommended to restricted roles.
- [ ] A saved preference changes the dashboard's recommended next action and can be edited without modifying rules or grants.
- [ ] No UI claims activation or successful delivery merely because a preference was saved.
- [ ] Existing camera wizard remains available on demand to admins; a goal can be selected before camera/provider setup.
- [ ] Backend, web interaction tests, production build and CI pass.

## Dependencies and boundaries

Build on #202/#203 camera-access work. Phase 1 is the first executable slice; this issue remains open for later workflow/context/measurement work. #193 owns verified activation. Link progress to roadmap #200. No automatic audio enablement, billing, handover confirmation, live deployment or database migration is included.
