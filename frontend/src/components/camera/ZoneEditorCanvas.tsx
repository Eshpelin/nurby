"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { MotionZone } from "./types";

const ZONE_COLORS: Record<string, { fill: string; stroke: string; dot: string; ui: string }> = {
  include:  { fill: "rgba(34,197,94,0.2)",  stroke: "#22c55e", dot: "bg-green-500",  ui: "border-green-500 bg-green-500/10 text-green-400" },
  exclude:  { fill: "rgba(239,68,68,0.2)",  stroke: "#ef4444", dot: "bg-red-500",    ui: "border-red-500 bg-red-500/10 text-red-400" },
  loiter:   { fill: "rgba(245,158,11,0.2)", stroke: "#f59e0b", dot: "bg-amber-500",  ui: "border-amber-500 bg-amber-500/10 text-amber-400" },
  tripwire: { fill: "rgba(99,102,241,0.2)", stroke: "#6366f1", dot: "bg-indigo-500", ui: "border-indigo-500 bg-indigo-500/10 text-indigo-400" },
  zone:     { fill: "rgba(14,165,233,0.2)", stroke: "#0ea5e9", dot: "bg-sky-500",    ui: "border-sky-500 bg-sky-500/10 text-sky-400" },
  veto:     { fill: "rgba(168,85,247,0.2)", stroke: "#a855f7", dot: "bg-purple-500", ui: "border-purple-500 bg-purple-500/10 text-purple-400" },
};

// Human labels + one-line explanations for the zone kind picker. Order is

const ZONE_KINDS: { value: MotionZone["type"]; label: string; desc: string }[] = [
  { value: "zone", label: "Named area",
    desc: "Draw and name an area (\"Driveway\"). Rules can then target it: person in Driveway. Nothing is hidden from the AI." },
  { value: "loiter", label: "Loiter area",
    desc: "Alert-ready area that tracks how long someone stays inside. Pair with a Loitering rule." },
  { value: "tripwire", label: "Tripwire",
    desc: "A line. Fires when something crosses it, with optional direction. Pair with a Tripwire rule." },
  { value: "include", label: "Watch only here",
    desc: "Mask: the AI sees ONLY these areas. Everything else is blacked out before detection, faces, and captions." },
  { value: "exclude", label: "Ignore this area",
    desc: "Mask: blacks the area out of everything the AI sees. For the neighbor's yard or a TV screen." },
  { value: "veto", label: "Veto area",
    desc: "While something is detected in here, ALL alerts on this camera pause. Kills headlight-flare false alarms on a wall." },
];

export function ZoneEditorCanvas({
  zones,
  onChange,
  width,
  height,
}: {
  zones: MotionZone[];
  onChange: (zones: MotionZone[]) => void;
  width: number;
  height: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [drawing, setDrawing] = useState(false);
  const [currentPoints, setCurrentPoints] = useState<number[][]>([]);
  const [zoneType, setZoneType] = useState<MotionZone["type"]>("zone");

  const canvasWidth = 480;
  const canvasHeight = Math.round((canvasWidth * height) / width) || 270;
  const scaleX = canvasWidth / width;
  const scaleY = canvasHeight / height;

  const drawZones = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvasWidth, canvasHeight);

    // Draw existing zones
    zones.forEach((zone) => {
      if (zone.points.length < 2) return;
      const colors = ZONE_COLORS[zone.type] || ZONE_COLORS.include;
      ctx.beginPath();
      ctx.moveTo(zone.points[0][0] * scaleX, zone.points[0][1] * scaleY);
      zone.points.forEach((p, i) => {
        if (i > 0) ctx.lineTo(p[0] * scaleX, p[1] * scaleY);
      });
      if (zone.type === "tripwire") {
        // Leave open. Draw as a thick line with an arrow indicator for direction.
        ctx.strokeStyle = colors.stroke;
        ctx.lineWidth = 3;
        ctx.stroke();
        // Arrow for direction ("in" default forward, "out" backward, "any" double-head).
        const a = [zone.points[0][0] * scaleX, zone.points[0][1] * scaleY];
        const b = [zone.points[1][0] * scaleX, zone.points[1][1] * scaleY];
        const mx = (a[0] + b[0]) / 2;
        const my = (a[1] + b[1]) / 2;
        const nx = -(b[1] - a[1]);
        const ny = (b[0] - a[0]);
        const nlen = Math.sqrt(nx * nx + ny * ny) || 1;
        const nxu = (nx / nlen) * 10;
        const nyu = (ny / nlen) * 10;
        const dir = zone.direction || "any";
        ctx.fillStyle = colors.stroke;
        ctx.beginPath();
        if (dir === "in" || dir === "any") {
          ctx.moveTo(mx, my);
          ctx.lineTo(mx + nxu - (b[0] - a[0]) * 0.03, my + nyu - (b[1] - a[1]) * 0.03);
          ctx.lineTo(mx + nxu + (b[0] - a[0]) * 0.03, my + nyu + (b[1] - a[1]) * 0.03);
          ctx.closePath();
        }
        if (dir === "out" || dir === "any") {
          ctx.moveTo(mx, my);
          ctx.lineTo(mx - nxu - (b[0] - a[0]) * 0.03, my - nyu - (b[1] - a[1]) * 0.03);
          ctx.lineTo(mx - nxu + (b[0] - a[0]) * 0.03, my - nyu + (b[1] - a[1]) * 0.03);
          ctx.closePath();
        }
        ctx.fill();
      } else {
        ctx.closePath();
        ctx.fillStyle = colors.fill;
        ctx.fill();
        ctx.strokeStyle = colors.stroke;
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Label
      const cx = zone.points.reduce((s, p) => s + p[0] * scaleX, 0) / zone.points.length;
      const cy = zone.points.reduce((s, p) => s + p[1] * scaleY, 0) / zone.points.length;
      ctx.fillStyle = "#fff";
      ctx.font = "11px monospace";
      ctx.textAlign = "center";
      ctx.fillText(zone.name, cx, cy);
    });

    // Draw current drawing
    if (currentPoints.length > 0) {
      const colors = ZONE_COLORS[zoneType] || ZONE_COLORS.include;
      ctx.beginPath();
      ctx.moveTo(currentPoints[0][0], currentPoints[0][1]);
      currentPoints.forEach((p, i) => {
        if (i > 0) ctx.lineTo(p[0], p[1]);
      });
      ctx.strokeStyle = colors.stroke;
      ctx.lineWidth = 2;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);

      // Draw points
      currentPoints.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p[0], p[1], 4, 0, Math.PI * 2);
        ctx.fillStyle = colors.stroke;
        ctx.fill();
      });
    }
  }, [zones, currentPoints, scaleX, scaleY, canvasWidth, canvasHeight, zoneType]);

  useEffect(() => {
    drawZones();
  }, [drawZones]);

  const commitZone = useCallback((points: number[][]) => {
    const scaledPoints = points.map((p) => [
      Math.round(p[0] / scaleX),
      Math.round(p[1] / scaleY),
    ]);
    const newZone: MotionZone = {
      name: `${
        zoneType === "tripwire" ? "Tripwire"
        : zoneType === "loiter" ? "Loiter"
        : zoneType === "veto" ? "Veto"
        : zoneType === "zone" ? "Area"
        : "Mask"
      } ${zones.length + 1}`,
      points: scaledPoints,
      type: zoneType,
    };
    if (zoneType === "loiter") newZone.loiter_threshold_seconds = 30;
    if (zoneType === "tripwire") newZone.direction = "any";
    onChange([...zones, newZone]);
    setDrawing(false);
    setCurrentPoints([]);
  }, [onChange, scaleX, scaleY, zoneType, zones]);

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;

    if (!drawing) {
      setDrawing(true);
      setCurrentPoints([[x, y]]);
      return;
    }
    const next = [...currentPoints, [x, y]];
    // Tripwire auto-finishes after 2 points.
    if (zoneType === "tripwire" && next.length === 2) {
      commitZone(next);
      return;
    }
    setCurrentPoints(next);
  };

  const finishZone = () => {
    if (zoneType === "tripwire") {
      if (currentPoints.length !== 2) return;
    } else if (currentPoints.length < 3) {
      return;
    }
    commitZone(currentPoints);
  };

  const removeZone = (index: number) => {
    onChange(zones.filter((_, i) => i !== index));
  };

  const updateZone = (index: number, patch: Partial<MotionZone>) => {
    onChange(zones.map((z, i) => (i === index ? { ...z, ...patch } : z)));
  };

  const needMin = zoneType === "tripwire" ? 2 : 3;
  const canFinish = currentPoints.length >= needMin;
  const hasInclude = zones.some((z) => z.type === "include");
  const hasExclude = zones.some((z) => z.type === "exclude");

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-2">
        {ZONE_KINDS.map((b) => (
          <button
            key={b.value}
            type="button"
            onClick={() => { setZoneType(b.value); setCurrentPoints([]); setDrawing(false); }}
            className={`text-left rounded-md border p-2.5 transition-colors ${
              zoneType === b.value ? ZONE_COLORS[b.value].ui : "border-border text-muted-foreground hover:text-foreground"
            }`}
          >
            <div className="flex items-center gap-1.5 mb-0.5">
              <span className={`w-2 h-2 rounded-full ${ZONE_COLORS[b.value].dot}`} />
              <span className="text-xs font-medium">{b.label}</span>
              {b.value === "zone" && (
                <span className="text-[9px] px-1 py-0.5 rounded bg-muted text-muted-foreground">recommended</span>
              )}
            </div>
            <div className="text-[10px] leading-snug opacity-80">{b.desc}</div>
          </button>
        ))}
      </div>
      {hasInclude && hasExclude && (
        <p className="text-[11px] text-warning">
          Heads up: you have both &quot;Watch only here&quot; and &quot;Ignore&quot; masks.
          Once a watch-only mask exists, everything outside it is already
          ignored, so the separate ignore areas are redundant. Keep one
          style or the other.
        </p>
      )}
      <div className="flex flex-wrap gap-2 mb-2">
        {drawing && (
          <button
            type="button"
            onClick={finishZone}
            disabled={!canFinish}
            className="px-2.5 py-1.5 text-xs rounded-md border border-accent bg-accent/10 text-accent-foreground disabled:opacity-50"
          >
            Finish ({currentPoints.length}/{needMin === 2 ? "2" : `≥${needMin}`})
          </button>
        )}
      </div>

      <canvas
        ref={canvasRef}
        width={canvasWidth}
        height={canvasHeight}
        onClick={handleCanvasClick}
        className="border border-border rounded-md cursor-crosshair bg-black/20"
      />

      <p className="text-[11px] text-muted-foreground">
        {zoneType === "tripwire"
          ? "Click two points to drop a tripwire line. Auto-finishes on the second click."
          : `Click to add points. Finish when done (minimum ${needMin} points).`}
      </p>

      {zones.length > 0 && (
        <div className="space-y-1.5">
          {zones.map((zone, i) => (
            <div key={i} className="text-xs px-2 py-1.5 rounded border border-border space-y-1.5">
              <div className="flex items-center gap-2">
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${ZONE_COLORS[zone.type]?.dot || "bg-muted"}`} />
                <input
                  type="text"
                  value={zone.name}
                  onChange={(e) => updateZone(i, { name: e.target.value })}
                  className="bg-transparent border-0 outline-none flex-1 min-w-0 font-medium focus:ring-1 focus:ring-accent rounded px-1"
                />
                <span className="text-muted-foreground">
                  {ZONE_KINDS.find((k) => k.value === zone.type)?.label || zone.type} · {zone.points.length} pts
                </span>
                <button
                  type="button"
                  onClick={() => removeZone(i)}
                  className="text-muted-foreground hover:text-red-400 transition-colors px-1"
                  aria-label="Remove zone"
                >×</button>
              </div>
              {zone.type === "loiter" && (
                <div className="flex items-center gap-2 pl-4">
                  <label className="text-muted-foreground">Fires after</label>
                  <input
                    type="number" min="1" max="3600"
                    value={zone.loiter_threshold_seconds ?? 30}
                    onChange={(e) => updateZone(i, { loiter_threshold_seconds: parseInt(e.target.value) || 30 })}
                    className="w-16 px-1.5 py-0.5 rounded bg-background border border-border text-xs"
                  />
                  <span className="text-muted-foreground">seconds inside the zone.</span>
                </div>
              )}
              {zone.type === "tripwire" && (
                <div className="flex items-center gap-2 pl-4">
                  <label className="text-muted-foreground">Direction</label>
                  <div className="flex gap-1">
                    {["any", "in", "out"].map((d) => (
                      <button
                        key={d}
                        type="button"
                        onClick={() => updateZone(i, { direction: d })}
                        className={`px-2 py-0.5 text-[11px] rounded border capitalize ${
                          (zone.direction || "any") === d
                            ? "border-indigo-500 bg-indigo-500/10 text-indigo-400"
                            : "border-border text-muted-foreground hover:bg-muted"
                        }`}
                      >{d}</button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

