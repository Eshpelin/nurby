"use client";

// Draws grounding boxes over a frame. Coordinates are normalized [0,1] from
// the API (resolution-independent), so they map straight to CSS percentages.
// Green throughout: there is no calibrated confidence to color-grade by
// (design §6), so we never imply one with a heatmap.

import type { ScanBox } from "@/lib/useDeepScan";

const ACCENT = "rgb(34,197,94)";

export function GroundingBoxOverlay({ boxes }: { boxes: ScanBox[] }) {
  if (!boxes.length) return null;
  return (
    <div className="absolute inset-0 pointer-events-none">
      {boxes.map((b, i) => {
        const [x1, y1, x2, y2] = b.bbox_norm;
        if (b.is_point) {
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: `${x1 * 100}%`,
                top: `${y1 * 100}%`,
                width: 10,
                height: 10,
                transform: "translate(-50%, -50%)",
                borderRadius: "50%",
                background: ACCENT,
                boxShadow: "0 0 0 2px rgba(0,0,0,0.55)",
              }}
            />
          );
        }
        return (
          <div
            key={i}
            style={{
              position: "absolute",
              left: `${x1 * 100}%`,
              top: `${y1 * 100}%`,
              width: `${(x2 - x1) * 100}%`,
              height: `${(y2 - y1) * 100}%`,
              border: `2px solid ${ACCENT}`,
              borderRadius: "3px",
            }}
          >
            <span
              style={{
                position: "absolute",
                top: "-16px",
                left: 0,
                fontSize: "10px",
                lineHeight: "14px",
                padding: "0 3px",
                backgroundColor: ACCENT,
                color: "#000",
                borderRadius: "2px",
                whiteSpace: "nowrap",
                fontWeight: 600,
              }}
            >
              {b.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}
