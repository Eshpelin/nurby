"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import type { PTZPreset } from "./types";

function HoldButton({
  onHold,
  onRelease,
  children,
  className,
}: {
  onHold: () => void;
  onRelease: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      onMouseDown={onHold}
      onMouseUp={onRelease}
      onMouseLeave={onRelease}
      onTouchStart={onHold}
      onTouchEnd={onRelease}
      className={className}
    >
      {children}
    </button>
  );
}


export function PTZControlPanel({ cameraId }: { cameraId: string }) {
  const { authFetch } = useAuth();
  const [presets, setPresets] = useState<PTZPreset[]>([]);
  const [speed, setSpeed] = useState(0.5);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchPresets = useCallback(async () => {
    try {
      const res = await authFetch(`/api/cameras/${cameraId}/ptz/presets`);
      if (res.ok) setPresets(await res.json());
    } catch {
      /* silent */
    }
  }, [cameraId]);

  useEffect(() => {
    fetchPresets();
  }, [fetchPresets]);

  const sendMove = useCallback(
    async (pan: number, tilt: number, zoom: number) => {
      try {
        await authFetch(`/api/cameras/${cameraId}/ptz/move`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pan, tilt, zoom, speed }),
        });
      } catch {
        /* silent */
      }
    },
    [cameraId, speed]
  );

  const sendStop = useCallback(async () => {
    try {
      await authFetch(`/api/cameras/${cameraId}/ptz/stop`, { method: "POST" });
    } catch {
      /* silent */
    }
  }, [cameraId]);

  const startHold = useCallback(
    (pan: number, tilt: number, zoom: number) => {
      sendMove(pan, tilt, zoom);
      intervalRef.current = setInterval(() => sendMove(pan, tilt, zoom), 200);
    },
    [sendMove]
  );

  const stopHold = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    sendStop();
  }, [sendStop]);

  const goToPreset = useCallback(
    async (token: string) => {
      try {
        await authFetch(`/api/cameras/${cameraId}/ptz/goto`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ preset_token: token }),
        });
      } catch {
        /* silent */
      }
    },
    [cameraId]
  );

  const btnClass =
    "w-10 h-10 flex items-center justify-center rounded-md border border-border bg-card hover:bg-muted transition-colors text-sm font-medium";

  return (
    <div className="space-y-4">
      {/* Directional pad */}
      <div className="flex flex-col items-center gap-1">
        <HoldButton onHold={() => startHold(0, 1, 0)} onRelease={stopHold} className={btnClass}>
          ↑
        </HoldButton>
        <div className="flex gap-1">
          <HoldButton onHold={() => startHold(-1, 0, 0)} onRelease={stopHold} className={btnClass}>
            ←
          </HoldButton>
          <button
            type="button"
            onClick={() => sendStop()}
            className={`${btnClass} text-muted-foreground`}
          >
            ●
          </button>
          <HoldButton onHold={() => startHold(1, 0, 0)} onRelease={stopHold} className={btnClass}>
            →
          </HoldButton>
        </div>
        <HoldButton onHold={() => startHold(0, -1, 0)} onRelease={stopHold} className={btnClass}>
          ↓
        </HoldButton>
      </div>

      {/* Zoom */}
      <div className="flex items-center gap-2 justify-center">
        <HoldButton onHold={() => startHold(0, 0, -1)} onRelease={stopHold} className={btnClass}>
          −
        </HoldButton>
        <span className="text-xs text-muted-foreground">Zoom</span>
        <HoldButton onHold={() => startHold(0, 0, 1)} onRelease={stopHold} className={btnClass}>
          +
        </HoldButton>
      </div>

      {/* Speed */}
      <div className="flex items-center gap-3">
        <span className="text-xs text-muted-foreground">Speed</span>
        <input
          type="range"
          min={0.1}
          max={1}
          step={0.1}
          value={speed}
          onChange={(e) => setSpeed(Number(e.target.value))}
          className="flex-1 accent-accent"
        />
        <span className="font-mono text-xs text-muted-foreground w-8 text-right">
          {(speed * 100).toFixed(0)}%
        </span>
      </div>

      {/* Presets */}
      {presets.length > 0 && (
        <div>
          <div className="text-xs text-muted-foreground mb-2">Presets</div>
          <div className="flex flex-wrap gap-1">
            {presets.map((p) => (
              <button
                key={p.token}
                type="button"
                onClick={() => goToPreset(p.token)}
                className="px-2 py-1 text-xs rounded border border-border hover:bg-muted transition-colors"
              >
                {p.name || p.token}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

