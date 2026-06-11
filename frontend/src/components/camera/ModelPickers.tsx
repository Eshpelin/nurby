"use client";

import { useEffect, useRef, useState } from "react";
import { DETECTION_MODEL_CATALOG } from "./detection-models";

export function DetectionModelSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [customMode, setCustomMode] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const match = DETECTION_MODEL_CATALOG.find((m) => m.value === value);
  const isCustom = !match && value.length > 0;

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  if (customMode || isCustom) {
    return (
      <div className="flex-1 flex items-center gap-1">
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="custom-model.pt"
          className="flex-1 px-2 py-1 text-xs font-mono rounded border border-border bg-card text-foreground focus:outline-none focus:ring-1 focus:ring-accent"
          autoFocus
        />
        <button
          type="button"
          onClick={() => { setCustomMode(false); onChange("yolov8n.pt"); }}
          className="text-[10px] text-muted-foreground hover:text-foreground px-1.5"
          title="Pick from catalog instead"
        >Catalog</button>
      </div>
    );
  }

  return (
    <div ref={ref} className="flex-1 relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between gap-2 px-2 py-1 rounded border border-border bg-card text-xs hover:border-muted-foreground/40 focus:outline-none focus:border-accent transition-colors"
      >
        <span className="min-w-0 text-left">
          <span className="block truncate font-medium">{match?.label || "Pick a model"}</span>
          <span className="block truncate text-[10px] text-muted-foreground font-mono">{match?.value || value}</span>
        </span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`text-muted-foreground flex-shrink-0 transition-transform ${open ? "rotate-180" : ""}`}>
          <path d="m6 9 6 6 6-6"/>
        </svg>
      </button>
      {open && (
        <div className="absolute z-30 mt-1 w-[28rem] max-w-[80vw] right-0 rounded-md border border-border bg-card shadow-lg max-h-80 overflow-y-auto py-1">
          {(["yolo-world", "yolo11", "yolov8", "oiv7", "yolo11-seg", "rtdetr"] as const).map((fam) => {
            const group = DETECTION_MODEL_CATALOG.filter((m) => m.family === fam);
            if (group.length === 0) return null;
            const famLabel = {
              "yolov8": "YOLOv8 (COCO 80 classes)",
              "yolo11": "YOLO11 (COCO 80 classes, newer)",
              "yolo-world": "YOLO-World (open vocabulary, prompt-driven)",
              "oiv7": "Open Images V7 (600+ classes)",
              "yolo11-seg": "YOLO11 Segmentation (masks for tighter blur)",
              "rtdetr": "RT-DETR (transformer detector)",
            }[fam];
            return (
              <div key={fam} className="py-1">
                <div className="px-3 py-1 text-[10px] uppercase tracking-wider text-muted-foreground font-medium">{famLabel}</div>
                {group.map((m) => {
                  const selected = m.value === value;
                  return (
                    <button
                      key={m.value}
                      type="button"
                      onClick={() => { onChange(m.value); setOpen(false); }}
                      className={`w-full text-left px-3 py-1.5 flex items-start justify-between gap-2 hover:bg-muted/60 ${selected ? "bg-muted/40" : ""}`}
                    >
                      <span className="min-w-0">
                        <span className="block text-xs font-medium truncate">{m.label}</span>
                        <span className="block text-[10px] text-muted-foreground truncate">{m.hint}</span>
                        <span className="block text-[10px] text-muted-foreground/70 font-mono">{m.value}</span>
                      </span>
                      {selected && (
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="text-accent flex-shrink-0 mt-0.5">
                          <path d="M20 6 9 17l-5-5"/>
                        </svg>
                      )}
                    </button>
                  );
                })}
              </div>
            );
          })}
          <div className="border-t border-border mt-1 pt-1">
            <button
              type="button"
              onClick={() => { setOpen(false); setCustomMode(true); onChange(""); }}
              className="w-full text-left px-3 py-1.5 text-xs text-muted-foreground hover:bg-muted/60 hover:text-foreground"
            >Enter custom model filename.</button>
          </div>
        </div>
      )}
    </div>
  );
}

export function LabelPicker({
  selected,
  available,
  loading,
  onChange,
  placeholder,
  activeModels,
  onAddModel,
}: {
  selected: string[];
  available: string[];
  loading: boolean;
  onChange: (labels: string[]) => void;
  placeholder?: string;
  activeModels?: string[];
  onAddModel?: (model: string) => void;
}) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const remaining = available.filter((l) => !selected.includes(l));
  const filtered = q ? remaining.filter((l) => l.toLowerCase().includes(q)) : remaining;

  const needsModel = (activeModels?.length || 0) === 0;

  return (
    <div>
      {activeModels && activeModels.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-2">
          <span className="text-[10px] text-muted-foreground self-center">Labels sourced from.</span>
          {activeModels.map((m) => (
            <span key={m} className="px-1.5 py-0.5 text-[10px] font-mono rounded border border-border bg-muted/30 text-muted-foreground">
              {m}
            </span>
          ))}
        </div>
      )}

      {needsModel && onAddModel && (
        <div className="mb-2 rounded-md border border-dashed border-amber-500/40 bg-amber-500/5 p-2.5">
          <p className="text-[11px] text-amber-300 mb-1.5">
            Pick a detection model first. Labels come from whichever model you choose.
          </p>
          <DetectionModelSelect
            value="yolov8n.pt"
            onChange={(v) => { if (v) onAddModel(v); }}
          />
        </div>
      )}

      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mb-2">
          {selected.map((label) => (
            <span
              key={label}
              className="inline-flex items-center gap-1 px-2 py-0.5 text-[11px] rounded-md border border-accent bg-accent/10 text-accent-foreground"
            >
              {label}
              <button
                type="button"
                onClick={() => onChange(selected.filter((l) => l !== label))}
                className="text-accent-foreground/60 hover:text-accent-foreground ml-0.5"
              >×</button>
            </span>
          ))}
        </div>
      )}
      <input
        type="text"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={placeholder || "Search labels."}
        className="w-full px-2 py-1.5 text-xs rounded-md border border-border bg-background focus:outline-none focus:border-accent"
        onKeyDown={(e) => {
          if (e.key === "Enter" && q) {
            e.preventDefault();
            const exact = available.find((l) => l.toLowerCase() === q);
            const pick = exact || q;
            if (!selected.includes(pick)) onChange([...selected, pick]);
            setQuery("");
          }
        }}
      />
      <div className="mt-2 max-h-40 overflow-y-auto rounded-md border border-border bg-background/40 p-1.5">
        {loading ? (
          <p className="text-[11px] text-muted-foreground px-1 py-2">Loading labels from model.</p>
        ) : available.length === 0 ? (
          <p className="text-[11px] text-muted-foreground px-1 py-2">
            {needsModel
              ? "Pick a model above to see its labels."
              : "Model loaded no classes. First-run download may still be in progress, or the model is open-vocabulary. Type a label and press Enter."}
          </p>
        ) : filtered.length === 0 ? (
          <p className="text-[11px] text-muted-foreground px-1 py-2">
            {q ? "No matches. Press Enter to add as custom." : "All labels added."}
          </p>
        ) : (
          <div className="flex flex-wrap gap-1">
            {filtered.slice(0, 80).map((label) => (
              <button
                key={label}
                type="button"
                onClick={() => onChange([...selected, label])}
                className="px-1.5 py-0.5 text-[10px] rounded border border-border text-muted-foreground hover:border-accent hover:text-accent-foreground transition-colors"
              >+ {label}</button>
            ))}
            {filtered.length > 80 && (
              <span className="text-[10px] text-muted-foreground self-center px-1">
                +{filtered.length - 80} more. Keep typing to narrow.
              </span>
            )}
          </div>
        )}
      </div>
      <p className="text-[10px] text-muted-foreground mt-1">
        {available.length > 0 ? `${available.length} labels from selected model${available.length === 1 ? "" : "s"}.` : ""}
      </p>
    </div>
  );
}
