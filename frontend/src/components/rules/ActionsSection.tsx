"use client";

import {
  ACTION_TYPES,
  HTTP_METHODS,
  AUTH_TYPES,
  TEMPLATE_VARIABLES,
  DEFAULT_PAYLOAD_TEMPLATE,
  TELEGRAM_TEMPLATE_VARS,
  TELEGRAM_DEFAULT_BUTTONS,
  TELEGRAM_BUTTON_ACTION_OPTIONS,
  TELEGRAM_BUTTON_DURATION_DEFAULTS,
  VLM_PROVIDERS,
  VLM_SCHEMA_PRESETS,
  isValidHttpUrlOrTemplate,
  defaultDraftForType,
  availableVarsBefore,
  MAX_ACTIONS_PER_RULE,
  type ActionType,
  type ActionDraft,
  type WebhookDraft,
  type BroadcastDraft,
  type NotifyDraft,
  type EmailDraft,
  type TelegramDraft,
  type VlmCallDraft,
  type TelegramButton,
  type TelegramButtonAction,
  type TelegramChannelOption,
} from "./types";
import { StyledSelect } from "./StyledSelect";
import { useState } from "react";

export interface ActionsSectionProps {
  telegramChannels: TelegramChannelOption[];
  telegramChannelsLoading: boolean;

  formActions: ActionDraft[];
  setFormActions: (updater: ActionDraft[] | ((prev: ActionDraft[]) => ActionDraft[])) => void;

  // Per-card error message keyed by card index (var-ref validation).
  cardErrors: Record<number, string>;
}

// ── Per-type editor helpers ──
// Inline rather than split into separate files. The split is left as a
// follow-up. functionally these blocks were the originals lifted out of
// the old single-action section, now driven by a draft + onChange pair.

interface CardCtx {
  draft: ActionDraft;
  index: number;
  updateDraft: (patch: Partial<ActionDraft>) => void;
  availableVars: { name: string; keys: string[] }[];
  telegramChannels: TelegramChannelOption[];
  telegramChannelsLoading: boolean;
}

// Insert-var dropdown. Appears next to template inputs when prior
// vlm_call cards declared outputs.
function VarInserter({
  vars,
  onInsert,
}: {
  vars: { name: string; keys: string[] }[];
  onInsert: (token: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (vars.length === 0) return null;
  return (
    <div className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="px-1.5 py-0.5 text-[10px] rounded border border-border hover:bg-muted text-muted-foreground"
      >
        Insert var
      </button>
      {open && (
        <div
          className="absolute z-10 mt-1 bg-card border border-border rounded shadow-lg min-w-[180px] max-h-64 overflow-y-auto"
          onMouseLeave={() => setOpen(false)}
        >
          {vars.map((v) => (
            <div key={v.name} className="py-1">
              <button
                type="button"
                onClick={() => {
                  onInsert(`{{vars.${v.name}}}`);
                  setOpen(false);
                }}
                className="block w-full text-left px-2 py-0.5 text-[10px] font-mono hover:bg-muted"
              >
                {`{{vars.${v.name}}}`}
              </button>
              {v.keys.map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => {
                    onInsert(`{{vars.${v.name}.${k}}}`);
                    setOpen(false);
                  }}
                  className="block w-full text-left pl-4 pr-2 py-0.5 text-[10px] font-mono hover:bg-muted"
                >
                  {`{{vars.${v.name}.${k}}}`}
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function WebhookBody({ ctx }: { ctx: CardCtx }) {
  const d = ctx.draft as WebhookDraft;
  const set = (patch: Partial<WebhookDraft>) => ctx.updateDraft(patch);
  return (
    <div className="space-y-3">
      {d.type === "api_call" && (
        <div>
          <label className="text-xs text-muted-foreground block mb-1">HTTP Method</label>
          <div className="flex gap-1">
            {HTTP_METHODS.map((m) => (
              <button
                key={m}
                type="button"
                onClick={() => set({ method: m })}
                className={`px-3 py-1.5 text-xs rounded border transition-colors ${
                  d.method === m
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-border hover:bg-muted"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
      )}
      <input
        type="url"
        value={d.url}
        onChange={(e) => set({ url: e.target.value })}
        className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
        placeholder="https://api.example.com/endpoint"
      />
      <div>
        <label className="text-xs text-muted-foreground block mb-1.5">Authentication</label>
        <div className="flex gap-1 mb-2">
          {AUTH_TYPES.map((at) => (
            <button
              key={at.value}
              type="button"
              onClick={() => set({ authType: at.value })}
              className={`px-2 py-1.5 text-xs rounded border transition-colors ${
                d.authType === at.value
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border hover:bg-muted"
              }`}
            >
              {at.label}
            </button>
          ))}
        </div>
        {d.authType === "bearer" && (
          <input
            type="password"
            value={d.authToken}
            onChange={(e) => set({ authToken: e.target.value })}
            className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
            placeholder="Bearer token"
          />
        )}
        {d.authType === "api_key" && (
          <div className="flex gap-2">
            <input
              type="text"
              value={d.authHeader}
              onChange={(e) => set({ authHeader: e.target.value })}
              className="w-1/3 px-3 py-2 rounded-md bg-background border border-border text-sm"
              placeholder="Header name"
            />
            <input
              type="password"
              value={d.authKey}
              onChange={(e) => set({ authKey: e.target.value })}
              className="flex-1 px-3 py-2 rounded-md bg-background border border-border text-sm"
              placeholder="API key value"
            />
          </div>
        )}
        {d.authType === "basic" && (
          <div className="flex gap-2">
            <input
              type="text"
              value={d.authUser}
              onChange={(e) => set({ authUser: e.target.value })}
              className="flex-1 px-3 py-2 rounded-md bg-background border border-border text-sm"
              placeholder="Username"
            />
            <input
              type="password"
              value={d.authPass}
              onChange={(e) => set({ authPass: e.target.value })}
              className="flex-1 px-3 py-2 rounded-md bg-background border border-border text-sm"
              placeholder="Password"
            />
          </div>
        )}
      </div>
      <div>
        <label className="flex items-center gap-2 cursor-pointer mb-2">
          <input
            type="checkbox"
            checked={d.useCustomPayload}
            onChange={(e) => {
              const checked = e.target.checked;
              set({
                useCustomPayload: checked,
                payloadTemplate:
                  checked && !d.payloadTemplate ? DEFAULT_PAYLOAD_TEMPLATE : d.payloadTemplate,
                payloadError: "",
              });
            }}
            className="accent-green-500"
          />
          <span className="text-xs">Custom payload template</span>
        </label>
        {d.useCustomPayload && (
          <div className="space-y-2">
            <textarea
              value={d.payloadTemplate}
              onChange={(e) => {
                const v = e.target.value;
                let err = "";
                try {
                  if (v.trim()) JSON.parse(v);
                } catch {
                  err = "Invalid JSON";
                }
                set({ payloadTemplate: v, payloadError: err });
              }}
              rows={8}
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-xs font-mono focus:outline-none focus:border-accent resize-y"
              placeholder={DEFAULT_PAYLOAD_TEMPLATE}
              spellCheck={false}
            />
            {d.payloadError && (
              <div className="text-[10px] text-red-400">{d.payloadError}</div>
            )}
            <div className="flex items-center gap-2 flex-wrap">
              <div className="text-[10px] text-muted-foreground">Vars.</div>
              {TEMPLATE_VARIABLES.map((v) => (
                <button
                  key={v.key}
                  type="button"
                  title={v.desc}
                  onClick={() =>
                    set({ payloadTemplate: d.payloadTemplate + `"{{${v.key}}}"` })
                  }
                  className="px-1.5 py-0.5 text-[10px] rounded border border-border hover:bg-muted text-muted-foreground font-mono transition-colors"
                >
                  {`{{${v.key}}}`}
                </button>
              ))}
              <VarInserter
                vars={ctx.availableVars}
                onInsert={(tok) =>
                  set({ payloadTemplate: d.payloadTemplate + `"${tok}"` })
                }
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function BroadcastBody({ ctx }: { ctx: CardCtx }) {
  const d = ctx.draft as BroadcastDraft;
  const set = (patch: Partial<BroadcastDraft>) => ctx.updateDraft(patch);
  return (
    <div>
      <label className="flex items-center gap-2 cursor-pointer mb-2">
        <input
          type="checkbox"
          checked={d.useCustomPayload}
          onChange={(e) => {
            const checked = e.target.checked;
            set({
              useCustomPayload: checked,
              payloadTemplate:
                checked && !d.payloadTemplate ? DEFAULT_PAYLOAD_TEMPLATE : d.payloadTemplate,
              payloadError: "",
            });
          }}
          className="accent-green-500"
        />
        <span className="text-xs">Custom broadcast payload</span>
      </label>
      {d.useCustomPayload && (
        <div className="space-y-2">
          <textarea
            value={d.payloadTemplate}
            onChange={(e) => {
              const v = e.target.value;
              let err = "";
              try {
                if (v.trim()) JSON.parse(v);
              } catch {
                err = "Invalid JSON";
              }
              set({ payloadTemplate: v, payloadError: err });
            }}
            rows={6}
            className="w-full px-3 py-2 rounded-md bg-background border border-border text-xs font-mono focus:outline-none focus:border-accent resize-y"
            placeholder={DEFAULT_PAYLOAD_TEMPLATE}
            spellCheck={false}
          />
          {d.payloadError && (
            <div className="text-[10px] text-red-400">{d.payloadError}</div>
          )}
          <div className="flex flex-wrap gap-1 items-center">
            {TEMPLATE_VARIABLES.map((v) => (
              <button
                key={v.key}
                type="button"
                title={v.desc}
                onClick={() =>
                  set({ payloadTemplate: d.payloadTemplate + `"{{${v.key}}}"` })
                }
                className="px-1.5 py-0.5 text-[10px] rounded border border-border hover:bg-muted text-muted-foreground font-mono"
              >
                {`{{${v.key}}}`}
              </button>
            ))}
            <VarInserter
              vars={ctx.availableVars}
              onInsert={(tok) =>
                set({ payloadTemplate: d.payloadTemplate + `"${tok}"` })
              }
            />
          </div>
        </div>
      )}
    </div>
  );
}

function NotifyBody({ ctx }: { ctx: CardCtx }) {
  const d = ctx.draft as NotifyDraft;
  const set = (patch: Partial<NotifyDraft>) => ctx.updateDraft(patch);
  return (
    <>
      <input
        type="text"
        value={d.message}
        onChange={(e) => set({ message: e.target.value })}
        className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
        placeholder="Rule '{rule_name}' triggered"
      />
      <StyledSelect
        value={d.severity}
        options={[
          { value: "info", label: "Info" },
          { value: "warning", label: "Warning" },
          { value: "critical", label: "Critical" },
        ]}
        onChange={(v) => set({ severity: v })}
      />
      <div className="flex items-center gap-2">
        <VarInserter
          vars={ctx.availableVars}
          onInsert={(tok) => set({ message: d.message + tok })}
        />
      </div>
    </>
  );
}

function EmailBody({ ctx }: { ctx: CardCtx }) {
  const d = ctx.draft as EmailDraft;
  const set = (patch: Partial<EmailDraft>) => ctx.updateDraft(patch);
  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs text-muted-foreground block mb-1">Recipient</label>
        <input
          type="email"
          value={d.to}
          onChange={(e) => set({ to: e.target.value })}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
          placeholder="user@example.com"
        />
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">Subject template</label>
        <input
          type="text"
          value={d.subject}
          onChange={(e) => set({ subject: e.target.value })}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
          placeholder="Nurby alert. {{rule_name}}"
        />
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">Body template</label>
        <textarea
          value={d.body}
          onChange={(e) => set({ body: e.target.value })}
          rows={4}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm resize-y"
          placeholder="Rule {{rule_name}} fired at {{timestamp}} on camera {{camera_id}}"
        />
      </div>
      <div className="flex flex-wrap gap-1 items-center">
        {TEMPLATE_VARIABLES.map((v) => (
          <button
            key={v.key}
            type="button"
            title={v.desc}
            onClick={() => set({ body: d.body + `{{${v.key}}}` })}
            className="px-1.5 py-0.5 text-[10px] rounded border border-border hover:bg-muted text-muted-foreground font-mono"
          >
            {`{{${v.key}}}`}
          </button>
        ))}
        <VarInserter
          vars={ctx.availableVars}
          onInsert={(tok) => set({ body: d.body + tok })}
        />
      </div>
      <div className="text-[10px] text-muted-foreground bg-muted/50 rounded px-2 py-1.5">
        SMTP must be configured in Settings for email delivery to work.
      </div>
    </div>
  );
}

function TelegramBody({ ctx }: { ctx: CardCtx }) {
  const d = ctx.draft as TelegramDraft;
  const set = (patch: Partial<TelegramDraft>) => ctx.updateDraft(patch);
  const setButtons = (
    fn: (prev: TelegramButton[]) => TelegramButton[],
  ) => set({ buttons: fn(d.buttons) });
  const paired = ctx.telegramChannels.filter((c) => c.enabled && c.pairing_status === "paired");
  if (ctx.telegramChannelsLoading) {
    return <div className="text-xs text-muted-foreground">Loading Telegram channels.</div>;
  }
  if (paired.length === 0) {
    return (
      <div className="text-xs text-muted-foreground bg-muted/40 border border-border rounded px-3 py-2">
        No Telegram channels yet. Add one in{" "}
        <a href="/settings" className="underline text-accent">
          Settings → Notifications →
        </a>
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <div>
        <label className="text-xs text-muted-foreground block mb-1">Telegram channel</label>
        <StyledSelect
          value={d.channelId}
          onChange={(v) => set({ channelId: v })}
          options={[
            { value: "", label: "Pick a channel..." },
            ...paired
              .slice()
              .sort((a, b) => a.label.localeCompare(b.label))
              .map((c) => ({
                value: c.id,
                label: `${c.label} · ${c.chat_title || "@" + (c.bot_username || "")}${
                  c.owned_by_me === false
                    ? ` (shared by ${c.owner_display_name || "other"})`
                    : ""
                }`,
              })),
          ]}
        />
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">Message template</label>
        <textarea
          value={d.template}
          onChange={(e) => set({ template: e.target.value })}
          rows={4}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm resize-y"
          placeholder="<b>{rule_name}</b> on {camera_name}"
        />
        <div className="text-[10px] text-muted-foreground mt-1">
          HTML formatting is supported (e.g. &lt;b&gt;bold&lt;/b&gt;). Variables. click to insert.
        </div>
        <div className="flex flex-wrap gap-1 mt-1 items-center">
          {TELEGRAM_TEMPLATE_VARS.map((v) => (
            <button
              key={v.key}
              type="button"
              title={v.desc}
              onClick={() => set({ template: d.template + `{${v.key}}` })}
              className="px-1.5 py-0.5 text-[10px] rounded border border-border hover:bg-muted text-muted-foreground font-mono"
            >
              {`{${v.key}}`}
            </button>
          ))}
          <VarInserter
            vars={ctx.availableVars}
            onInsert={(tok) => set({ template: d.template + tok })}
          />
        </div>
      </div>
      <div className="flex flex-wrap gap-3">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={d.silent}
            onChange={(e) => set({ silent: e.target.checked })}
            className="accent-green-500"
          />
          <span className="text-xs">Silent (no sound)</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={d.includeThumbnail}
            onChange={(e) => set({ includeThumbnail: e.target.checked })}
            className="accent-green-500"
          />
          <span className="text-xs">
            Include snapshot
            <span className="text-muted-foreground ml-1">(photo attachment)</span>
          </span>
        </label>
      </div>
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <label className="text-xs text-muted-foreground">
            Inline buttons ({d.buttons.length}/4)
          </label>
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => set({ buttons: TELEGRAM_DEFAULT_BUTTONS })}
              className="text-[10px] px-2 py-0.5 rounded border border-border hover:bg-muted text-muted-foreground"
            >
              Reset to defaults
            </button>
            <button
              type="button"
              disabled={d.buttons.length >= 4}
              onClick={() =>
                setButtons((prev) => [...prev, { label: "Action", action: "ack" }])
              }
              className="text-[10px] px-2 py-0.5 rounded border border-border hover:bg-muted text-muted-foreground disabled:opacity-50 disabled:cursor-not-allowed"
            >
              + Add button
            </button>
          </div>
        </div>
        {d.buttons.length === 0 ? (
          <div className="text-[11px] text-muted-foreground bg-muted/40 rounded px-2 py-1.5">
            No buttons. Recipients see a plain message.
          </div>
        ) : (
          <div className="space-y-1.5">
            {d.buttons.map((btn, i) => (
              <div
                key={i}
                className="flex flex-wrap gap-2 items-center bg-muted/30 border border-border rounded px-2 py-1.5"
              >
                <input
                  type="text"
                  value={btn.label}
                  onChange={(e) => {
                    const v = e.target.value;
                    setButtons((prev) =>
                      prev.map((b, idx) => (idx === i ? { ...b, label: v } : b)),
                    );
                  }}
                  placeholder="Label"
                  className="flex-1 min-w-[120px] px-2 py-1 rounded bg-background border border-border text-xs"
                />
                <StyledSelect
                  value={btn.action}
                  onChange={(val) => {
                    const action = val as TelegramButtonAction;
                    setButtons((prev) =>
                      prev.map((b, idx) => {
                        if (idx !== i) return b;
                        const next: TelegramButton = { ...b, action };
                        next.duration_seconds = TELEGRAM_BUTTON_DURATION_DEFAULTS[action];
                        if (action === "open" && !next.url) next.url = "{event_url}";
                        if (action !== "open") delete next.url;
                        return next;
                      }),
                    );
                  }}
                  options={TELEGRAM_BUTTON_ACTION_OPTIONS.map((o) => ({
                    value: o.value,
                    label: o.label,
                  }))}
                />
                {(btn.action === "mute_event" || btn.action === "snooze_rule") && (
                  <div className="flex items-center gap-1">
                    <input
                      type="range"
                      min={60}
                      max={3600}
                      step={60}
                      value={btn.duration_seconds ?? 600}
                      onChange={(e) => {
                        const v = parseInt(e.target.value) || 600;
                        setButtons((prev) =>
                          prev.map((b, idx) =>
                            idx === i ? { ...b, duration_seconds: v } : b,
                          ),
                        );
                      }}
                      className="w-24"
                    />
                    <span className="text-[10px] text-muted-foreground font-mono w-12">
                      {Math.round((btn.duration_seconds ?? 600) / 60)}m
                    </span>
                  </div>
                )}
                {btn.action === "open" && (
                  <input
                    type="text"
                    value={btn.url ?? ""}
                    onChange={(e) => {
                      const v = e.target.value;
                      setButtons((prev) =>
                        prev.map((b, idx) => (idx === i ? { ...b, url: v } : b)),
                      );
                    }}
                    placeholder="https://... or {event_url}"
                    className={`flex-1 min-w-[160px] px-2 py-1 rounded bg-background border text-xs ${
                      btn.url && !isValidHttpUrlOrTemplate(btn.url)
                        ? "border-red-500"
                        : "border-border"
                    }`}
                  />
                )}
                <button
                  type="button"
                  onClick={() => setButtons((prev) => prev.filter((_, idx) => idx !== i))}
                  className="text-[10px] px-2 py-1 rounded border border-border hover:bg-red-500/10 hover:border-red-500/40 text-muted-foreground"
                  title="Remove button"
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function VlmBody({ ctx }: { ctx: CardCtx }) {
  const d = ctx.draft as VlmCallDraft;
  const set = (patch: Partial<VlmCallDraft>) => ctx.updateDraft(patch);
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Provider</label>
          <StyledSelect
            value={d.provider}
            options={VLM_PROVIDERS}
            onChange={(v) => set({ provider: v })}
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Model</label>
          <input
            type="text"
            value={d.model}
            onChange={(e) => set({ model: e.target.value })}
            className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
            placeholder="gpt-4o-mini"
          />
        </div>
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">System prompt</label>
        <textarea
          value={d.system}
          onChange={(e) => set({ system: e.target.value })}
          rows={2}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono resize-y"
          placeholder="{{defaults.system}}"
        />
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">User prompt</label>
        <textarea
          value={d.prompt}
          onChange={(e) => set({ prompt: e.target.value })}
          rows={3}
          className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm resize-y"
        />
        <div className="flex flex-wrap gap-1 mt-1">
          {["description", "faces", "objects", "camera_name", "timestamp"].map((k) => (
            <button
              key={k}
              type="button"
              onClick={() => set({ prompt: d.prompt + ` {{${k}}}` })}
              className="px-1.5 py-0.5 text-[10px] rounded border border-border hover:bg-muted text-muted-foreground font-mono"
            >{`{{${k}}}`}</button>
          ))}
        </div>
      </div>
      <label className="flex items-center gap-2 cursor-pointer">
        <input
          type="checkbox"
          checked={d.attachImage}
          onChange={(e) => set({ attachImage: e.target.checked })}
          className="accent-green-500"
        />
        <span className="text-xs">Attach snapshot image</span>
      </label>
      <div>
        <label className="flex items-center gap-2 cursor-pointer mb-1">
          <input
            type="checkbox"
            checked={d.useSchema}
            onChange={(e) => set({ useSchema: e.target.checked })}
            className="accent-green-500"
          />
          <span className="text-xs">Structured JSON output</span>
        </label>
        {d.useSchema && (
          <div className="space-y-2">
            <div className="flex flex-wrap gap-1">
              {[
                { key: "threat", label: "Threat level" },
                { key: "notify", label: "Notify yes/no" },
                { key: "intent", label: "Intent classifier" },
                { key: "entities", label: "Entity counts" },
              ].map((p) => (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => set({ schemaText: VLM_SCHEMA_PRESETS[p.key] })}
                  className="px-2 py-1 text-[11px] rounded border border-border hover:bg-muted text-muted-foreground"
                >
                  {p.label}
                </button>
              ))}
            </div>
            <textarea
              value={d.schemaText}
              onChange={(e) => set({ schemaText: e.target.value })}
              rows={8}
              className="w-full px-3 py-2 rounded-md bg-background border border-border text-xs font-mono resize-y"
            />
          </div>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Output variable</label>
          <input
            type="text"
            value={d.output}
            onChange={(e) => set({ output: e.target.value.replace(/[^\w]/g, "") })}
            className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm font-mono"
            placeholder="result"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Max retries</label>
          <input
            type="number"
            min={0}
            max={3}
            value={d.maxRetries}
            onChange={(e) => set({ maxRetries: e.target.value })}
            className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
          />
        </div>
        <div>
          <label className="text-xs text-muted-foreground block mb-1">Timeout (ms)</label>
          <input
            type="number"
            min={1000}
            step={1000}
            value={d.timeoutMs}
            onChange={(e) => set({ timeoutMs: e.target.value })}
            className="w-full px-3 py-2 rounded-md bg-background border border-border text-sm"
          />
        </div>
      </div>
      <div>
        <label className="text-xs text-muted-foreground block mb-1">On error</label>
        <StyledSelect
          value={d.onError}
          options={[
            { value: "continue", label: "Continue chain" },
            { value: "stop", label: "Stop chain" },
            { value: "fallback", label: "Use fallback value" },
          ]}
          onChange={(v) => set({ onError: v })}
        />
      </div>
      <div className="text-[10px] text-muted-foreground bg-muted/50 rounded px-2 py-1.5">
        Reference the result in later actions with {"{{"}vars.{d.output || "result"}.field{"}}"}.
      </div>
    </div>
  );
}

// ── Single action card ──

function ActionCard({
  draft,
  index,
  total,
  collapsed,
  setCollapsed,
  onUpdate,
  onMove,
  onDelete,
  onChangeType,
  availableVars,
  telegramChannels,
  telegramChannelsLoading,
  errorMessage,
}: {
  draft: ActionDraft;
  index: number;
  total: number;
  collapsed: boolean;
  setCollapsed: (v: boolean) => void;
  onUpdate: (patch: Partial<ActionDraft>) => void;
  onMove: (delta: -1 | 1) => void;
  onDelete: () => void;
  onChangeType: (type: ActionType) => void;
  availableVars: { name: string; keys: string[] }[];
  telegramChannels: TelegramChannelOption[];
  telegramChannelsLoading: boolean;
  errorMessage?: string;
}) {
  const typeLabel =
    ACTION_TYPES.find((a) => a.value === draft.type)?.label || draft.type;
  const ctx: CardCtx = {
    draft,
    index,
    updateDraft: onUpdate,
    availableVars,
    telegramChannels,
    telegramChannelsLoading,
  };
  return (
    <fieldset
      className={`border rounded-md p-3 space-y-3 ${
        errorMessage ? "border-red-500/60" : "border-border"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="px-1.5 py-0.5 text-[10px] rounded bg-muted text-zinc-300 font-mono">
            {index + 1}
          </span>
          <span className="text-xs px-1.5 py-0.5 rounded border border-border text-muted-foreground">
            {typeLabel}
          </span>
          <button
            type="button"
            onClick={() => setCollapsed(!collapsed)}
            className="text-[10px] px-1.5 py-0.5 rounded border border-border hover:bg-muted text-muted-foreground"
            title={collapsed ? "Expand" : "Collapse"}
          >
            {collapsed ? "▸" : "▾"}
          </button>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            disabled={index === 0}
            onClick={() => onMove(-1)}
            className="text-[10px] px-1.5 py-0.5 rounded border border-border hover:bg-muted text-muted-foreground disabled:opacity-30"
            title="Move up"
          >
            ↑
          </button>
          <button
            type="button"
            disabled={index === total - 1}
            onClick={() => onMove(1)}
            className="text-[10px] px-1.5 py-0.5 rounded border border-border hover:bg-muted text-muted-foreground disabled:opacity-30"
            title="Move down"
          >
            ↓
          </button>
          <button
            type="button"
            onClick={onDelete}
            className="text-[10px] px-1.5 py-0.5 rounded border border-red-800 text-red-400 hover:bg-red-900/30"
            title="Delete action"
          >
            ✕
          </button>
        </div>
      </div>
      {!collapsed && (
        <>
          <StyledSelect
            value={draft.type}
            options={ACTION_TYPES.map((a) => ({ value: a.value, label: a.label }))}
            onChange={(v) => onChangeType(v as ActionType)}
          />
          {(draft.type === "webhook" || draft.type === "api_call") && (
            <WebhookBody ctx={ctx} />
          )}
          {draft.type === "broadcast" && <BroadcastBody ctx={ctx} />}
          {draft.type === "notify" && <NotifyBody ctx={ctx} />}
          {draft.type === "email" && <EmailBody ctx={ctx} />}
          {draft.type === "telegram" && <TelegramBody ctx={ctx} />}
          {draft.type === "vlm_call" && <VlmBody ctx={ctx} />}
        </>
      )}
      {errorMessage && (
        <div className="text-[11px] text-red-400">{errorMessage}</div>
      )}
    </fieldset>
  );
}

// ── Chain editor (default export) ──

export function ActionsSection(props: ActionsSectionProps) {
  const { telegramChannels, telegramChannelsLoading, formActions, setFormActions, cardErrors } =
    props;
  const [collapsed, setCollapsed] = useState<Record<number, boolean>>({});

  const updateAt = (i: number, patch: Partial<ActionDraft>) => {
    setFormActions((prev) =>
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      prev.map((d, idx) => (idx === i ? ({ ...d, ...patch } as ActionDraft) : d)),
    );
  };
  const moveAt = (i: number, delta: -1 | 1) => {
    setFormActions((prev) => {
      const j = i + delta;
      if (j < 0 || j >= prev.length) return prev;
      const next = prev.slice();
      const tmp = next[i];
      next[i] = next[j];
      next[j] = tmp;
      return next;
    });
  };
  const deleteAt = (i: number) => {
    setFormActions((prev) => (prev.length <= 1 ? prev : prev.filter((_, idx) => idx !== i)));
  };
  const changeTypeAt = (i: number, t: ActionType) => {
    setFormActions((prev) =>
      prev.map((d, idx) => (idx === i ? defaultDraftForType(t) : d)),
    );
  };
  const addAction = () => {
    setFormActions((prev) =>
      prev.length >= MAX_ACTIONS_PER_RULE
        ? prev
        : [...prev, defaultDraftForType("notify")],
    );
  };

  return (
    <fieldset className="border border-border rounded-md p-3 space-y-3">
      <legend className="text-xs font-medium text-muted-foreground px-1">
        Actions ({formActions.length})
      </legend>
      {formActions.map((draft, i) => (
        <ActionCard
          key={i}
          draft={draft}
          index={i}
          total={formActions.length}
          collapsed={!!collapsed[i]}
          setCollapsed={(v) => setCollapsed((m) => ({ ...m, [i]: v }))}
          onUpdate={(patch) => updateAt(i, patch)}
          onMove={(delta) => moveAt(i, delta)}
          onDelete={() => deleteAt(i)}
          onChangeType={(t) => changeTypeAt(i, t)}
          availableVars={availableVarsBefore(formActions, i)}
          telegramChannels={telegramChannels}
          telegramChannelsLoading={telegramChannelsLoading}
          errorMessage={cardErrors[i]}
        />
      ))}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={addAction}
          disabled={formActions.length >= MAX_ACTIONS_PER_RULE}
          className="px-2 py-1 text-xs rounded border border-dashed border-border hover:bg-muted text-muted-foreground disabled:opacity-50"
        >
          + Add action
        </button>
        {formActions.length >= MAX_ACTIONS_PER_RULE && (
          <span className="text-[10px] text-muted-foreground">
            Limit of {MAX_ACTIONS_PER_RULE} actions reached.
          </span>
        )}
      </div>
    </fieldset>
  );
}
