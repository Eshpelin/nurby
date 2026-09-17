import { useState } from "react";

function StatusDot({ status }: { status: string }) {
  const color =
    status === "recording"
      ? "bg-danger"
      : status === "live"
        ? "bg-green-500"
        : "bg-gray-500";
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${color} ${status !== "offline" ? "pulse-dot" : ""}`}
    />
  );
}

function Section({
  title,
  children,
  description,
  advanced = false,
}: {
  title: string;
  children: React.ReactNode;
  description?: string;
  /**
   * Collapsed by default (docs/settings-layers.md). Web folds at the
   * section level: a section whose fields are all pipeline tuning sits
   * behind a disclosure so it does not carry the same weight as
   * "Blur areas". Every field stays reachable.
   */
  advanced?: boolean;
}) {
  if (advanced) {
    return (
      <details className="group rounded-lg border border-border bg-card">
        <summary className="cursor-pointer list-none px-5 py-4 flex items-center justify-between gap-3">
          <span>
            <span className="text-sm font-semibold">{title}</span>
            <span className="ml-2 text-[10px] uppercase tracking-wider text-muted-foreground">Advanced</span>
            {description && <p className="text-xs text-muted-foreground mt-1">{description}</p>}
          </span>
          <span className="text-muted-foreground transition-transform group-open:rotate-180" aria-hidden>⌄</span>
        </summary>
        <div className="px-5 pb-5 space-y-4">{children}</div>
      </details>
    );
  }
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <h3 className="text-sm font-semibold mb-1">{title}</h3>
      {description && (
        <p className="text-xs text-muted-foreground mb-4">{description}</p>
      )}
      {!description && <div className="mb-4" />}
      <div className="space-y-4">{children}</div>
    </div>
  );
}

function FieldRow({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-[180px_1fr] gap-4 items-start">
      <div>
        <label className="text-sm text-foreground">{label}</label>
        {hint && <p className="text-[11px] text-muted-foreground mt-0.5">{hint}</p>}
      </div>
      <div>{children}</div>
    </div>
  );
}

function KeywordChipInput({
  values,
  onChange,
  placeholder,
}: {
  values: string[];
  onChange: (v: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");
  const commit = () => {
    const cleaned = draft
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (cleaned.length === 0) return;
    const next = Array.from(new Set([...values, ...cleaned]));
    onChange(next);
    setDraft("");
  };
  return (
    <div className="flex flex-wrap items-center gap-1.5 min-h-[2.25rem] px-2 py-1 rounded-md border border-border bg-background focus-within:border-accent">
      {values.map((v) => (
        <span
          key={v}
          className="inline-flex items-center gap-1 px-1.5 py-0.5 text-xs rounded bg-accent/15 text-accent border border-accent/30"
        >
          {v}
          <button
            type="button"
            onClick={() => onChange(values.filter((x) => x !== v))}
            className="text-accent/70 hover:text-accent"
            aria-label={`Remove ${v}`}
          >
            ×
          </button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            commit();
          } else if (e.key === "Backspace" && !draft && values.length > 0) {
            onChange(values.slice(0, -1));
          }
        }}
        onBlur={commit}
        placeholder={values.length === 0 ? placeholder : ""}
        className="flex-1 min-w-[8rem] bg-transparent text-sm focus:outline-none"
      />
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
        checked ? "bg-accent" : "bg-muted"
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
          checked ? "translate-x-[18px]" : "translate-x-[3px]"
        }`}
      />
      {label && (
        <span className="ml-11 text-sm text-muted-foreground whitespace-nowrap">
          {label}
        </span>
      )}
    </button>
  );
}

const inputClass =
  "w-full px-3 py-2 text-sm rounded-md border border-border bg-background text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-accent";

export { StatusDot, Section, FieldRow, KeywordChipInput, Toggle, inputClass };
