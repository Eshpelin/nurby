# Expected activity (#215)

The first implementation slice is the pure evaluator in
`services/perception/expected_activity.py`. It defines the safety contract
for scheduled expectations:

- a matching sighting satisfies the window;
- a covered window with no sighting is a violation and includes last-seen
  evidence;
- outage, degraded, or unprocessed coverage produces `unknown`, never a false
  absence alert;
- expectations only apply on their configured weekdays.

The existing association worker already performs a conservative daily absence
sweep for learned person/vehicle habits. The remaining integration work for
this issue is to persist user-defined windows, expose CRUD in Settings, run
this evaluator from the scheduler after the grace period, and render satisfied
versus violated expectations in the digest.
