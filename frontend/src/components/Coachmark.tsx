"use client";

import { useEffect, useState, type ReactNode, type RefObject } from "react";
import { createPortal } from "react-dom";

interface Props {
  // The real control this coach-mark points at. Anchoring by ref keeps it
  // tied to an element the wizard actually renders, so it never guesses at a
  // selector on another page.
  targetRef: RefObject<HTMLElement | null>;
  children: ReactNode;
  onDismiss: () => void;
  // Where the popover sits relative to the target. Falls back to the other
  // side when there isn't room.
  placement?: "top" | "bottom";
}

interface Box { top: number; left: number; width: number; height: number }

// A lightweight, in-house spotlight. No tour engine, no third-party SaaS:
// just a ring drawn over one element and a small popover beside it, both
// positioned from the live bounding box and re-measured on scroll/resize.
export function Coachmark({ targetRef, children, onDismiss, placement = "bottom" }: Props) {
  const [box, setBox] = useState<Box | null>(null);

  useEffect(() => {
    const el = targetRef.current;
    if (!el) return;
    const measure = () => {
      const r = el.getBoundingClientRect();
      setBox({ top: r.top, left: r.left, width: r.width, height: r.height });
    };
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onDismiss(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
      window.removeEventListener("keydown", onKey);
    };
  }, [targetRef, onDismiss]);

  if (typeof document === "undefined" || !box) return null;

  // Keep the popover on-screen: below the target unless that would push it off
  // the bottom, in which case flip above.
  const below = placement === "bottom" && box.top + box.height + 96 < window.innerHeight;
  const popTop = below ? box.top + box.height + 10 : box.top - 10;
  const popLeft = Math.max(12, Math.min(box.left, window.innerWidth - 288 - 12));

  return createPortal(
    <div className="pointer-events-none fixed inset-0 z-[60]" role="presentation">
      {/* Spotlight ring over the real control. */}
      <div
        aria-hidden
        className="absolute rounded-lg ring-2 ring-accent ring-offset-2 ring-offset-background motion-safe:animate-pulse"
        style={{ top: box.top - 4, left: box.left - 4, width: box.width + 8, height: box.height + 8 }}
      />
      {/* Popover with the hint. */}
      <div
        role="dialog"
        aria-label="Tip"
        className="pointer-events-auto absolute w-72 rounded-lg border border-border bg-card p-3 text-sm shadow-2xl motion-safe:animate-[coachIn_.16s_ease-out]"
        style={below ? { top: popTop, left: popLeft } : { top: popTop, left: popLeft, transform: "translateY(-100%)" }}
      >
        <style>{`@keyframes coachIn{from{opacity:.4;transform:translateY(${below ? "-4px" : "calc(-100% + 4px)"})}to{opacity:1}}`}</style>
        <div className="flex items-start justify-between gap-2">
          <div className="text-muted-foreground">{children}</div>
          <button
            type="button"
            onClick={onDismiss}
            aria-label="Dismiss tip"
            className="-mr-1 -mt-1 shrink-0 rounded p-1 text-muted-foreground hover:text-foreground"
          >
            ×
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
