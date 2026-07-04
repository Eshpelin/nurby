"use client";

// Presentational dropdown for the @-mention autocomplete. Anchored to
// the composer's relative wrapper (not the caret): robust across input
// and textarea and fine at phone widths.

import type { Mentionable } from "@/lib/useMentionables";

const KIND_BADGE: Record<Mentionable["kind"], { icon: string; label: string }> = {
  person: { icon: "👤", label: "Person" },
  camera: { icon: "📹", label: "Camera" },
  telegram_channel: { icon: "💬", label: "Telegram" },
  device: { icon: "📟", label: "Device" },
};

export function MentionDropdown({
  open,
  items,
  highlight,
  onSelect,
  placement = "above",
}: {
  open: boolean;
  items: Mentionable[];
  highlight: number;
  onSelect: (item: Mentionable) => void;
  placement?: "above" | "below";
}) {
  if (!open) return null;
  return (
    <div
      className={`absolute left-0 right-0 z-30 ${
        placement === "above" ? "bottom-full mb-1" : "top-full mt-1"
      } rounded-md border border-border bg-card-elevated shadow-xl overflow-hidden`}
      role="listbox"
    >
      {items.map((item, i) => {
        const badge = KIND_BADGE[item.kind];
        return (
          <button
            key={`${item.kind}:${item.id}`}
            type="button"
            role="option"
            aria-selected={i === highlight}
            // mousedown, not click: keep focus (and the active token) in
            // the field until select() has spliced the text.
            onMouseDown={(e) => {
              e.preventDefault();
              onSelect(item);
            }}
            className={`w-full flex items-center gap-2 px-2.5 py-1.5 text-left text-xs ${
              i === highlight ? "bg-muted" : "hover:bg-muted/60"
            }`}
          >
            <span className="text-sm leading-none">{badge.icon}</span>
            <span className="font-medium truncate">{item.name}</span>
            <span className="ml-auto text-[10px] text-muted-foreground truncate">
              {item.hint || badge.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
