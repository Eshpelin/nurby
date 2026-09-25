# AI cost visibility

Settings → AI usage shows the last seven days of estimated VLM spend, call
count, token totals, and the highest-cost camera/workload rows. The report is
available at `GET /api/agent/usage/report?days=7` for admins; other users see
their own Ask activity and camera analysis they are allowed to view.

Values are estimates, not invoices. They use the provider/model pricing table
in `services/agent/budget.py`; local Ollama providers are estimated at zero.
Each result carries the pricing note so users do not mistake the estimate for
provider billing.

The first reporting slice covers persisted analyzer calls and Ask runs. It
subtracts analyzer rows from their parent Ask run before adding the residual,
so one VLM call is not counted twice. Rule-level perception accounting for
caption/refiner calls remains a follow-up: those paths need to persist their
token usage and rule id before they can appear in the same report or be used
for degradation guardrails.
