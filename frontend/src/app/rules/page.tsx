"use client";

import { useCallback, useEffect, useState } from "react";

interface Rule {
  id: string;
  name: string;
  enabled: boolean;
  trigger_pattern: Record<string, unknown>;
  conditions: Record<string, unknown> | null;
  actions: Record<string, unknown> | Record<string, unknown>[];
  cooldown_seconds: number;
  created_at: string;
}

const TRIGGER_TYPES = [
  { value: "object_detected", label: "Object detected" },
  { value: "face_detected", label: "Face detected" },
  { value: "face_recognized", label: "Face recognized" },
  { value: "face_unknown", label: "Unknown face" },
  { value: "motion", label: "Motion" },
  { value: "any", label: "Any observation" },
];

const OBJECT_LABELS = [
  "person", "car", "truck", "bicycle", "motorcycle",
  "dog", "cat", "bird", "backpack", "handbag",
  "suitcase", "umbrella",
];

const ACTION_TYPES = [
  { value: "webhook", label: "Webhook" },
  { value: "broadcast", label: "WebSocket broadcast" },
  { value: "notify", label: "Notification" },
];

function describeTrigger(pattern: Record<string, unknown>): string {
  const t = pattern.type as string;
  if (t === "object_detected") {
    const label = pattern.label as string | undefined;
    return label ? `When "${label}" detected` : "When any object detected";
  }
  if (t === "face_detected") return "When any face detected";
  if (t === "face_recognized") {
    const pid = pattern.person_id as string | undefined;
    return pid ? `When person ${pid.slice(0, 8)} recognized` : "When any known face recognized";
  }
  if (t === "face_unknown") return "When unknown face detected";
  if (t === "motion") {
    const ms = pattern.min_score as number | undefined;
    return ms ? `When motion score >= ${ms}` : "When motion detected";
  }
  if (t === "any") return "On every observation";
  return "Unknown trigger";
}

function describeActions(actions: Record<string, unknown> | Record<string, unknown>[]): string {
  const list = Array.isArray(actions) ? actions : [actions];
  return list
    .map((a) => {
      if (a.type === "webhook") return `POST to ${(a.url as string) || "..."}`;
      if (a.type === "broadcast") return "Broadcast via WebSocket";
      if (a.type === "notify") return `Notify. "${(a.message as string) || "..."}"`;
      return String(a.type);
    })
    .join(", ");
}

export default function RulesPage() {
  const [rules, setRules] = useState<Rule[]>([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editRule, setEditRule] = useState<Rule | null>(null);
  const [selectedRule, setSelectedRule] = useState<Rule | null>(null);

  // Form state
  const [formName, setFormName] = useState("");
  const [formEnabled, setFormEnabled] = useState(true);
  const [formTriggerType, setFormTriggerType] = useState("object_detected");
  const [formTriggerLabel, setFormTriggerLabel] = useState("");
  const [formTriggerPersonId, setFormTriggerPersonId] = useState("");
  const [formTriggerMinScore, setFormTriggerMinScore] = useState("0.05");
  const [formCondCamera, setFormCondCamera] = useState("");
  const [formCondTimeAfter, setFormCondTimeAfter] = useState("");
  const [formCondTimeBefore, setFormCondTimeBefore] = useState("");
  const [formCondMinConf, setFormCondMinConf] = useState("");
  const [formActionType, setFormActionType] = useState("notify");
  const [formActionUrl, setFormActionUrl] = useState("");
  const [formActionMessage, setFormActionMessage] = useState("");
  const [formActionSeverity, setFormActionSeverity] = useState("info");
  const [formCooldown, setFormCooldown] = useState("300");
  const [formError, setFormError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const fetchRules = useCallback(async () => {
    try {
      const res = await fetch("/api/rules");
      if (res.ok) setRules(await res.json());
    } catch {
      /* silent */
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRules();
  }, [fetchRules]);

  const resetForm = () => {
    setFormName("");
    setFormEnabled(true);
    setFormTriggerType("object_detected");
    setFormTriggerLabel("");
    setFormTriggerPersonId("");
    setFormTriggerMinScore("0.05");
    setFormCondCamera("");
    setFormCondTimeAfter("");
    setFormCondTimeBefore("");
    setFormCondMinConf("");
    setFormActionType("notify");
    setFormActionUrl("");
    setFormActionMessage("");
    setFormActionSeverity("info");
    setFormCooldown("300");
    setFormError("");
  };

  const openCreate = () => {
    setEditRule(null);
    resetForm();
    setShowModal(true);
  };

  const openEdit = (r: Rule) => {
    setEditRule(r);
    setFormName(r.name);
    setFormEnabled(r.enabled);

    const tp = r.trigger_pattern;
    setFormTriggerType((tp.type as string) || "any");
    setFormTriggerLabel((tp.label as string) || "");
    setFormTriggerPersonId((tp.person_id as string) || "");
    setFormTriggerMinScore(String(tp.min_score ?? "0.05"));

    const cond = r.conditions || {};
    setFormCondCamera((cond.camera_id as string) || "");
    setFormCondTimeAfter((cond.time_after as string) || "");
    setFormCondTimeBefore((cond.time_before as string) || "");
    setFormCondMinConf(cond.min_confidence ? String(cond.min_confidence) : "");

    const acts = Array.isArray(r.actions) ? r.actions[0] : r.actions;
    setFormActionType((acts?.type as string) || "notify");
    setFormActionUrl((acts?.url as string) || "");
    setFormActionMessage((acts?.message as string) || "");
    setFormActionSeverity((acts?.severity as string) || "info");
    setFormCooldown(String(r.cooldown_seconds));
    setFormError("");
    setShowModal(true);
  };

  const buildPayload = () => {
    const trigger_pattern: Record<string, unknown> = { type: formTriggerType };
    if (formTriggerType === "object_detected" && formTriggerLabel) {
      trigger_pattern.label = formTriggerLabel;
    }
    if (formTriggerType === "face_recognized" && formTriggerPersonId) {
      trigger_pattern.person_id = formTriggerPersonId;
    }
    if (formTriggerType === "motion" && formTriggerMinScore) {
      trigger_pattern.min_score = parseFloat(formTriggerMinScore);
    }

    const conditions: Record<string, unknown> = {};
    if (formCondCamera) conditions.camera_id = formCondCamera;
    if (formCondTimeAfter) conditions.time_after = formCondTimeAfter;
    if (formCondTimeBefore) conditions.time_before = formCondTimeBefore;
    if (formCondMinConf) conditions.min_confidence = parseFloat(formCondMinConf);

    const action: Record<string, unknown> = { type: formActionType };
    if (formActionType === "webhook") action.url = formActionUrl;
    if (formActionType === "notify") {
      action.message = formActionMessage || "Rule '{rule_name}' triggered";
      action.severity = formActionSeverity;
    }

    return {
      name: formName.trim(),
      enabled: formEnabled,
      trigger_pattern,
      conditions: Object.keys(conditions).length > 0 ? conditions : null,
      actions: action,
      cooldown_seconds: parseInt(formCooldown) || 300,
    };
  };

  const handleSubmit = async () => {
    if (!formName.trim()) {
      setFormError("Name is required");
      return;
    }
    if (formActionType === "webhook" && !formActionUrl.trim()) {
      setFormError("Webhook URL is required");
      return;
    }

    setSubmitting(true);
    setFormError("");
    const body = buildPayload();

    try {
      let res: Response;
      if (editRule) {
        res = await fetch(`/api/rules/${editRule.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } else {
        res = await fetch("/api/rules", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      }

      if (!res.ok) {
        setFormError("Failed to save rule");
        return;
      }

      setShowModal(false);
      fetchRules();
    } catch {
      setFormError("Network error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await fetch(`/api/rules/${id}`, { method: "DELETE" });
      if (selectedRule?.id === id) setSelectedRule(null);
      fetchRules();
    } catch {
      /* silent */
    }
  };

  const handleToggle = async (rule: Rule) => {
    try {
      await fetch(`/api/rules/${rule.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...rule, enabled: !rule.enabled }),
      });
      fetchRules();
    } catch {
      /* silent */
    }
  };

  return (
    <div className="px-6 py-6">
      <div className="flex items-baseline justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Rules</h1>
          <p className="text-sm text-muted-foreground mt-1">
            {rules.length} rule{rules.length !== 1 ? "s" : ""} configured
          </p>
        </div>
        <button
          onClick={openCreate}
          className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90"
        >
          + Create rule
        </button>
      </div>

      {loading ? (
        <div className="text-sm text-muted-foreground py-20 text-center">
          Loading.
        </div>
      ) : rules.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <div className="w-16 h-16 rounded-full border border-border flex items-center justify-center mb-4 text-muted-foreground text-2xl">
            ?
          </div>
          <p className="text-muted-foreground text-sm mb-4">
            No rules created yet. Rules let you define triggers, conditions,
            and actions to automate your monitoring.
          </p>
          <button
            onClick={openCreate}
            className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90"
          >
            + Create first rule
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-12 gap-6">
          {/* Rule list */}
          <section className="col-span-8 space-y-3">
            {rules.map((r) => (
              <div
                key={r.id}
                onClick={() => setSelectedRule(r)}
                className={`rounded-lg border p-4 cursor-pointer transition-colors ${
                  selectedRule?.id === r.id
                    ? "border-accent bg-card"
                    : "border-border bg-card hover:border-muted-foreground/30"
                }`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleToggle(r);
                      }}
                      className={`w-8 h-5 rounded-full relative transition-colors ${
                        r.enabled ? "bg-green-500" : "bg-muted"
                      }`}
                    >
                      <span
                        className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform ${
                          r.enabled ? "left-3.5" : "left-0.5"
                        }`}
                      />
                    </button>
                    <div>
                      <div className="font-medium">{r.name}</div>
                      <div className="text-xs text-muted-foreground mt-0.5">
                        {describeTrigger(r.trigger_pattern)}
                      </div>
                    </div>
                  </div>
                  <div className="flex gap-1">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        openEdit(r);
                      }}
                      className="px-2 py-1 text-xs rounded border border-border hover:bg-muted transition-colors"
                    >
                      Edit
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(r.id);
                      }}
                      className="px-2 py-1 text-xs rounded border border-red-800 text-red-400 hover:bg-red-900/30 transition-colors"
                    >
                      Del
                    </button>
                  </div>
                </div>
                <div className="mt-2 text-xs text-muted-foreground">
                  Actions. {describeActions(r.actions)}
                </div>
                {r.cooldown_seconds > 0 && (
                  <div className="mt-1 text-xs text-muted-foreground">
                    Cooldown. {r.cooldown_seconds}s
                  </div>
                )}
              </div>
            ))}
          </section>

          {/* Preview panel */}
          <aside className="col-span-4">
            <div className="sticky top-20 rounded-lg border border-border bg-card p-5">
              <div className="flex items-center gap-2 mb-4">
                <span className="w-1.5 h-1.5 rounded-full bg-accent pulse-dot" />
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  Preview
                </span>
              </div>
              {selectedRule ? (
                <div className="space-y-3 text-sm">
                  <div>
                    <span className="text-muted-foreground text-xs">Name</span>
                    <div className="font-medium">{selectedRule.name}</div>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">Status</span>
                    <div className="flex items-center gap-2">
                      <span
                        className={`w-2 h-2 rounded-full ${
                          selectedRule.enabled ? "bg-green-500" : "bg-yellow-500"
                        }`}
                      />
                      {selectedRule.enabled ? "Active" : "Disabled"}
                    </div>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">Trigger</span>
                    <div>{describeTrigger(selectedRule.trigger_pattern)}</div>
                  </div>
                  {selectedRule.conditions && Object.keys(selectedRule.conditions).length > 0 && (
                    <div>
                      <span className="text-muted-foreground text-xs">Conditions</span>
                      <div className="font-mono text-xs mt-1 bg-muted rounded p-2">
                        {JSON.stringify(selectedRule.conditions, null, 2)}
                      </div>
                    </div>
                  )}
                  <div>
                    <span className="text-muted-foreground text-xs">Actions</span>
                    <div>{describeActions(selectedRule.actions)}</div>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">Cooldown</span>
                    <div>{selectedRule.cooldown_seconds}s between fires</div>
                  </div>
                  <div>
                    <span className="text-muted-foreground text-xs">Created</span>
                    <div>{new Date(selectedRule.created_at).toLocaleString()}</div>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground leading-relaxed">
                  Select a rule to see its configuration preview.
                </p>
              )}
            </div>
          </aside>
        </div>
      )}

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setShowModal(false)}
          />
          <div className="relative bg-card border border-border rounded-lg p-6 w-full max-w-lg shadow-xl max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold mb-4">
              {editRule ? "Edit rule" : "Create rule"}
            </h2>

            <div className="space-y-4">
              {/* Name */}
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  Rule name
                </label>
                <input
                  type="text"
                  value={formName}
                  onChange={(e) => setFormName(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm focus:outline-none focus:border-accent"
                  placeholder="e.g. Person at front door"
                  autoFocus
                />
              </div>

              {/* Enabled */}
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={formEnabled}
                  onChange={(e) => setFormEnabled(e.target.checked)}
                  className="accent-green-500"
                />
                <span className="text-sm">Enabled</span>
              </label>

              {/* Trigger */}
              <fieldset className="border border-border rounded-md p-3 space-y-2">
                <legend className="text-xs font-medium text-muted-foreground px-1">
                  Trigger
                </legend>
                <select
                  value={formTriggerType}
                  onChange={(e) => setFormTriggerType(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                >
                  {TRIGGER_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>

                {formTriggerType === "object_detected" && (
                  <select
                    value={formTriggerLabel}
                    onChange={(e) => setFormTriggerLabel(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                  >
                    <option value="">Any object</option>
                    {OBJECT_LABELS.map((l) => (
                      <option key={l} value={l}>
                        {l}
                      </option>
                    ))}
                  </select>
                )}

                {formTriggerType === "face_recognized" && (
                  <input
                    type="text"
                    value={formTriggerPersonId}
                    onChange={(e) => setFormTriggerPersonId(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                    placeholder="Person ID (leave blank for any recognized face)"
                  />
                )}

                {formTriggerType === "motion" && (
                  <div>
                    <label className="text-xs text-muted-foreground">
                      Min motion score
                    </label>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      max="1"
                      value={formTriggerMinScore}
                      onChange={(e) => setFormTriggerMinScore(e.target.value)}
                      className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                    />
                  </div>
                )}
              </fieldset>

              {/* Conditions */}
              <fieldset className="border border-border rounded-md p-3 space-y-2">
                <legend className="text-xs font-medium text-muted-foreground px-1">
                  Conditions (optional)
                </legend>
                <div>
                  <label className="text-xs text-muted-foreground">Camera ID filter</label>
                  <input
                    type="text"
                    value={formCondCamera}
                    onChange={(e) => setFormCondCamera(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                    placeholder="Leave blank for all cameras"
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-xs text-muted-foreground">Active after</label>
                    <input
                      type="time"
                      value={formCondTimeAfter}
                      onChange={(e) => setFormCondTimeAfter(e.target.value)}
                      className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-muted-foreground">Active before</label>
                    <input
                      type="time"
                      value={formCondTimeBefore}
                      onChange={(e) => setFormCondTimeBefore(e.target.value)}
                      className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                    />
                  </div>
                </div>
                <div>
                  <label className="text-xs text-muted-foreground">Min confidence</label>
                  <input
                    type="number"
                    step="0.1"
                    min="0"
                    max="1"
                    value={formCondMinConf}
                    onChange={(e) => setFormCondMinConf(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                    placeholder="0.0 - 1.0"
                  />
                </div>
              </fieldset>

              {/* Action */}
              <fieldset className="border border-border rounded-md p-3 space-y-2">
                <legend className="text-xs font-medium text-muted-foreground px-1">
                  Action
                </legend>
                <select
                  value={formActionType}
                  onChange={(e) => setFormActionType(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                >
                  {ACTION_TYPES.map((a) => (
                    <option key={a.value} value={a.value}>
                      {a.label}
                    </option>
                  ))}
                </select>

                {formActionType === "webhook" && (
                  <input
                    type="url"
                    value={formActionUrl}
                    onChange={(e) => setFormActionUrl(e.target.value)}
                    className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                    placeholder="https://your-webhook.com/endpoint"
                  />
                )}

                {formActionType === "notify" && (
                  <>
                    <input
                      type="text"
                      value={formActionMessage}
                      onChange={(e) => setFormActionMessage(e.target.value)}
                      className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                      placeholder="Rule '{rule_name}' triggered"
                    />
                    <select
                      value={formActionSeverity}
                      onChange={(e) => setFormActionSeverity(e.target.value)}
                      className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                    >
                      <option value="info">Info</option>
                      <option value="warning">Warning</option>
                      <option value="critical">Critical</option>
                    </select>
                  </>
                )}
              </fieldset>

              {/* Cooldown */}
              <div>
                <label className="text-xs font-medium text-muted-foreground block mb-1">
                  Cooldown (seconds)
                </label>
                <input
                  type="number"
                  min="0"
                  value={formCooldown}
                  onChange={(e) => setFormCooldown(e.target.value)}
                  className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
                />
                <span className="text-xs text-muted-foreground">
                  Min time between fires for this rule
                </span>
              </div>

              {formError && (
                <div className="text-xs text-red-400">{formError}</div>
              )}
            </div>

            <div className="flex justify-end gap-2 mt-5">
              <button
                onClick={() => setShowModal(false)}
                className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={submitting}
                className="px-3 py-1.5 text-sm rounded-md bg-foreground text-background font-medium hover:opacity-90 disabled:opacity-50"
              >
                {submitting ? "Saving." : editRule ? "Save" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
