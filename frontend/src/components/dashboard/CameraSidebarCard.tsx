"use client";

/**
 * One camera's tile in the dashboard sidebar: its live frame, its status,
 * and the controls that only make sense while you are looking at it.
 */

import { useState, useEffect, useRef, type KeyboardEvent } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useWebcamPublisher } from "@/lib/webcam-publisher";
import { RetryCountdown } from "@/components/RetryCountdown";
import { LiveCaptionOverlay } from "@/components/LiveCaptionOverlay";
import { ActivityStrip } from "@/components/ActivityStrip";
import { AudioActiveDot } from "@/components/AudioActiveDot";
import { VLMStatusBadge } from "@/components/VLMStatusBadge";
import { SummarizeNowButton } from "@/components/SummarizeNowButton";
import { FindNowButton } from "@/components/dashboard/FindNowButton";
import { CameraStatsHover } from "@/components/CameraStatsHover";
import { timeAgo } from "@/lib/time";
  process.env.NEXT_PUBLIC_WEBRTC_URL || "http://localhost:8889";
import type { ActivityEvent, Camera } from "@/app/dashboard-types";
import { extractStreamName } from "@/app/dashboard-helpers";
import { AnalyzingShimmer, DEFAULT_FRAME_HEIGHT, DEFAULT_FRAME_WIDTH, DetectionOverlay, MiniPTZ, SignalBadge } from "@/components/dashboard/CameraOverlays";
import { WEBRTC_URL } from "@/app/dashboard-helpers";
import { useAuth } from "@/lib/auth";

export type CameraLayout = "single" | "double" | "list";
export function CameraSidebarCard({
  camera,
  selected,
  onClick,
  activityEvents,
  layout,
  fill = false,
}: {
  camera: Camera;
  selected: boolean;
  onClick: () => void;
  activityEvents: ActivityEvent[];
  layout: CameraLayout;
  // Wall mode: the tile fills its grid cell (no fixed 16:9, no footer) so
  // the wall can size each camera independently in width AND height.
  fill?: boolean;
}) {
  const router = useRouter();
  const [overlayVisible, setOverlayVisible] = useState(true);
  const [ptzOpen, setPtzOpen] = useState(false);
  const ptzCapable = camera.stream_type === "rtsp";
  // MediaMTX serves the muxed copy under a canonical slug (mux_slug on the
  // backend), NOT the camera's own URL path. rtsp/hls pull-mux under
  // cam-<id>; webcam/usb push under webcam-<id>. Using the URL's last path
  // segment ("stream1") requests a path MediaMTX does not have, so the tile
  // shows "stream not found".
  const streamName =
    camera.stream_type === "rtsp" || camera.stream_type === "hls"
      ? `cam-${camera.id}`
      : camera.stream_type === "webcam" || camera.stream_type === "usb"
        ? `webcam-${camera.id}`
        : extractStreamName(camera.stream_url);
  const iframeSrc = `${WEBRTC_URL}/${streamName}/`;
  // A remote-file camera (the demo, or any http(s) clip) is not muxed into
  // MediaMTX, so the WebRTC path would be empty and the tile black. The
  // browser can play the URL directly, so render a looping <video>. This
  // also means the demo shows footage in a second, independent of the
  // ingestion poll + connect cycle.
  const isRemoteFile =
    camera.stream_type === "file" && /^https?:\/\//.test(camera.stream_url);
  const { token } = useAuth();
  const isLocalFile = camera.stream_type === "file" && !isRemoteFile;
  const localFilePreview = isLocalFile && token
    ? `/api/cameras/${camera.id}/preview?token=${encodeURIComponent(token)}`
    : null;
  const isPlayableFile = isRemoteFile || Boolean(localFilePreview);

  // Webcam publisher state for this tile. If this tab owns the capture
  // we render the local MediaStream directly in a <video> element.
  const { publishers, resumeIntent } = useWebcamPublisher();
  const isWebcam = camera.stream_type === "webcam";
  const myPublisher = publishers.find((p) => p.cameraId === camera.id);
  const localStream = myPublisher?.status === "live" ? myPublisher.stream : null;
  const webcamVideoRef = useRef<HTMLVideoElement | null>(null);
  useEffect(() => {
    const el = webcamVideoRef.current;
    if (!el) return;
    if (localStream && el.srcObject !== localStream) {
      el.srcObject = localStream;
      el.play().catch(() => undefined);
    } else if (!localStream && el.srcObject) {
      el.srcObject = null;
    }
  }, [localStream]);
  const latestEvent = activityEvents[0];
  const frameW = camera.width || DEFAULT_FRAME_WIDTH;
  const frameH = camera.height || DEFAULT_FRAME_HEIGHT;

  // Activity stats
  const now = Date.now();
  const events1h = activityEvents.filter((e) => now - new Date(e.timestamp).getTime() < 3600000);
  const events24h = activityEvents.filter((e) => now - new Date(e.timestamp).getTime() < 86400000);
  const openCamera = () => router.push(`/cameras/${camera.id}`);
  const handleTileClick = () => {
    onClick();
    openCamera();
  };
  const handleTileKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openCamera();
    }
  };

  // List layout. Compact horizontal row
  if (layout === "list") {
    return (
      <div
        onClick={handleTileClick}
        onKeyDown={handleTileKeyDown}
        tabIndex={0}
        aria-label={`Open ${camera.name} camera`}
        className={`rounded-md border overflow-hidden cursor-pointer transition-colors group flex items-center gap-2.5 px-2.5 py-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${
          selected ? "border-accent bg-card" : "border-border bg-card hover:border-muted-foreground/30"
        }`}
      >
        {/* Tiny preview */}
        <div className="relative w-16 h-10 bg-black rounded overflow-hidden flex-shrink-0">
          {camera.audio_only ? (
            <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-emerald-900/30 to-zinc-900">
              <svg className="w-5 h-5 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </div>
          ) : isPlayableFile ? (
            <video src={isRemoteFile ? camera.stream_url : localFilePreview ?? undefined} autoPlay muted loop playsInline className="absolute inset-0 w-full h-full object-cover" />
          ) : isWebcam && localStream ? (
            <video ref={webcamVideoRef} autoPlay muted playsInline className="absolute inset-0 w-full h-full object-cover" />
          ) : camera.status !== "offline" ? (
            <iframe src={iframeSrc} className="absolute inset-0 w-full h-full border-0 pointer-events-none scale-[1.5] origin-center" allow="autoplay; encrypted-media" sandbox="allow-scripts allow-same-origin" />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center"><span className="text-[8px] text-muted-foreground font-mono">OFF</span></div>
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${camera.status === "recording" ? "bg-danger" : camera.status === "live" ? "bg-green-500" : "bg-gray-400"} ${camera.status !== "offline" ? "pulse-dot" : ""}`} />
            <span className="text-xs font-medium truncate">{camera.name}</span>
          </div>
          {latestEvent && (
            <div className="text-[10px] text-muted-foreground truncate mt-0.5">{latestEvent.summary} · {timeAgo(latestEvent.timestamp)}</div>
          )}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {events1h.length > 0 && <span className="text-[9px] font-mono text-accent bg-accent/10 px-1 py-0.5 rounded">{events1h.length} / 1h</span>}
          {events24h.length > 0 && <span className="text-[9px] font-mono text-muted-foreground bg-muted/50 px-1 py-0.5 rounded">{events24h.length} / 24h</span>}
        </div>
        <button type="button" aria-label={`Open ${camera.name} settings`} title="Open camera"
          onClick={(e) => { e.stopPropagation(); openCamera(); }}
          className="w-5 h-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground flex-shrink-0">
          <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></svg>
        </button>
      </div>
    );
  }

  // Card layout (single or double column). With fill=true (wall mode) the
  // tile stretches to its container and the feed fills it instead of locking
  // to 16:9, so the wall grid controls each camera's width and height.
  return (
    <div
      onClick={handleTileClick}
      onKeyDown={handleTileKeyDown}
      tabIndex={0}
      aria-label={`Open ${camera.name} camera`}
      className={`rounded-lg border overflow-hidden cursor-pointer transition-colors group focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent ${
        fill ? "h-full flex flex-col" : ""
      } ${
        selected ? "border-accent bg-card" : "border-border bg-card hover:border-muted-foreground/30"
      }`}
    >
      {/* Feed preview */}
      <div className={`relative bg-black ${fill ? "flex-1 min-h-0" : "aspect-video"}`}>
        {camera.audio_only ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-gradient-to-br from-emerald-950/40 via-zinc-950 to-zinc-900">
            <div className="relative">
              <span className="absolute inset-0 rounded-full animate-ping bg-emerald-500/30" />
              <svg className="relative w-12 h-12 text-emerald-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                <line x1="12" y1="19" x2="12" y2="23" />
                <line x1="8" y1="23" x2="16" y2="23" />
              </svg>
            </div>
            <div className="text-[10px] uppercase tracking-wider text-emerald-300/80">
              Audio-only mic
            </div>
            {camera.stream_type === "browser_mic" && (
              <Link
                href={`/mic/${camera.id}`}
                onClick={(e) => e.stopPropagation()}
                className="text-[11px] px-2.5 py-1 rounded-md border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10"
              >
                Open mic page →
              </Link>
            )}
          </div>
        ) : isPlayableFile ? (
          <video
            src={isRemoteFile ? camera.stream_url : localFilePreview ?? undefined}
            autoPlay
            muted
            loop
            playsInline
            className="absolute inset-0 w-full h-full object-contain"
          />
        ) : isWebcam && localStream ? (
          <video
            ref={webcamVideoRef}
            autoPlay
            muted
            playsInline
            className="absolute inset-0 w-full h-full object-contain"
          />
        ) : camera.status !== "offline" ? (
          <iframe
            src={iframeSrc}
            className="absolute inset-0 w-full h-full border-0 pointer-events-none"
            allow="autoplay; encrypted-media"
            sandbox="allow-scripts allow-same-origin"
          />
        ) : (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
            <span className="text-[10px] text-muted-foreground font-mono">OFFLINE</span>
            {!isWebcam && (camera.status_reason || camera.next_retry_at) && (
              <RetryCountdown
                className="text-[10px] text-center px-2"
                nextRetryAt={camera.next_retry_at}
                reason={camera.status_reason}
              />
            )}
            {isWebcam && myPublisher?.status === "needs-permission" && (
              <button
                onClick={(e) => { e.stopPropagation(); resumeIntent(camera.id); }}
                className="text-[11px] px-2.5 py-1 rounded-md bg-amber-500 text-black font-medium hover:bg-amber-400"
              >
                Enable camera
              </button>
            )}
            {isWebcam && myPublisher?.status === "connecting" && (
              <span className="text-[10px] text-amber-400">connecting.</span>
            )}
            {isWebcam && myPublisher?.status === "held-by-other-tab" && (
              <span className="text-[10px] text-muted-foreground">streaming in another tab</span>
            )}
          </div>
        )}

        {/* Detection bounding box overlay. Skipped for remote-file cameras
            (the demo). the browser plays the clip on its own clock while the
            perception worker decodes the same file independently, so the
            "latest" box would land on the wrong frame. Detections for these
            stay frame-accurate in the timeline (the thumbnail is the exact
            analyzed frame). Near-live cameras (rtsp/webrtc) keep the overlay. */}
        {camera.status !== "offline" && !isPlayableFile && (
          <DetectionOverlay cameraId={camera.id} visible={overlayVisible} frameWidth={frameW} frameHeight={frameH} />
        )}

        {/* AI-analyzing sweep while a VLM call is in flight for this camera */}
        {camera.status !== "offline" && <AnalyzingShimmer cameraId={camera.id} />}

        {/* Live traffic-signal colour readout for any "signal" zones */}
        {camera.status !== "offline" && <SignalBadge cameraId={camera.id} />}

        {/* Live caption overlay. Only when transcription enabled */}
        {camera.status !== "offline" && camera.audio_transcribe_enabled && (
          <LiveCaptionOverlay cameraId={camera.id} position="bottom" />
        )}

        {/* The HAR live current-activity strip used to sit here. It only ever
            rendered when person_actions arrived (HAR is off by default), so it
            was invisible while occupying the tile's activity slot. The seeker
            at the bottom of the tile is the one activity surface now. */}

        {/* Audio active dot + VLM thinking badge. Stack top-left so the
            two are visually grouped and out of the way of overlay
            controls top-right. */}
        {camera.status !== "offline" && (
          <div className="absolute top-1.5 left-1.5 z-10 flex items-center gap-1">
            {camera.audio_capture_enabled && <AudioActiveDot cameraId={camera.id} />}
            <VLMStatusBadge cameraId={camera.id} />
          </div>
        )}

        {/* Summarize now. Hover-revealed top-right control. */}
        {camera.status !== "offline" && (
          <SummarizeNowButton cameraId={camera.id} variant="tile" />
        )}

        {/* Find anything now. Hover-revealed magnifier: grounds a prompt
            against this camera's latest frame. */}
        {camera.status !== "offline" && (
          <FindNowButton cameraId={camera.id} cameraName={camera.name} />
        )}

        {/* Stats hover. FPS / resolution / VLM latency / drops. Quiet
            until the user hovers the tile. */}
        {camera.status !== "offline" && (
          <CameraStatsHover
            cameraId={camera.id}
            fps={camera.fps}
            width={camera.width}
            height={camera.height}
          />
        )}

        {/* Overlay toggle (eye icon) */}
        {camera.status !== "offline" && (
          <button
            onClick={(e) => { e.stopPropagation(); setOverlayVisible((v) => !v); }}
            aria-label={overlayVisible ? "Hide detections" : "Show detections"}
            className="absolute top-1.5 right-9 z-10 w-6 h-6 rounded-md bg-black/60 backdrop-blur-sm border border-white/10 flex items-center justify-center text-white/70 hover:text-white hover:bg-black/80 transition-colors"
            title={overlayVisible ? "Hide detections" : "Show detections"}
          >
            {overlayVisible ? (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
              </svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                <line x1="1" y1="1" x2="23" y2="23" />
              </svg>
            )}
          </button>
        )}

        {/* PTZ toggle (only shown for PTZ-capable RTSP cameras) */}
        {ptzCapable && camera.status !== "offline" && (
          <button
            onClick={(e) => { e.stopPropagation(); setPtzOpen((v) => !v); }}
            aria-label="Open PTZ controls"
            className={`absolute top-1.5 right-[4.25rem] z-10 w-6 h-6 rounded-md backdrop-blur-sm border border-white/10 flex items-center justify-center transition-colors ${
              ptzOpen ? "bg-accent text-black" : "bg-black/60 text-white/70 hover:text-white hover:bg-black/80"
            }`}
            title="PTZ control"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="5 9 2 12 5 15" />
              <polyline points="9 5 12 2 15 5" />
              <polyline points="15 19 12 22 9 19" />
              <polyline points="19 9 22 12 19 15" />
              <line x1="2" y1="12" x2="22" y2="12" />
              <line x1="12" y1="2" x2="12" y2="22" />
            </svg>
          </button>
        )}

        {/* Mini PTZ panel */}
        {ptzCapable && ptzOpen && camera.status !== "offline" && (
          <MiniPTZ cameraId={camera.id} onClose={() => setPtzOpen(false)} />
        )}

        {/* Settings gear */}
        <button
          type="button"
          aria-label={`Open ${camera.name} settings`}
          title="Open camera settings"
          onClick={(e) => { e.stopPropagation(); openCamera(); }}
          className="absolute top-1.5 right-1.5 z-10 w-6 h-6 rounded-md bg-black/60 backdrop-blur-sm border border-white/10 flex items-center justify-center text-white/70 hover:text-white hover:bg-black/80 transition-colors"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
            <circle cx="12" cy="12" r="3"/>
          </svg>
        </button>

        {/* Activity counters overlay */}
        {(events1h.length > 0 || events24h.length > 0) && (
          <div className="absolute top-1.5 left-1.5 z-10 flex gap-1">
            {events1h.length > 0 && <span className="text-[9px] font-mono bg-accent/80 text-black px-1 py-0.5 rounded backdrop-blur-sm">{events1h.length} / 1h</span>}
            {events24h.length > 0 && events1h.length === 0 && <span className="text-[9px] font-mono bg-black/60 text-white/80 px-1 py-0.5 rounded backdrop-blur-sm">{events24h.length} / 24h</span>}
          </div>
        )}

        {/* Seeker + status/name overlay at the bottom of the video. The strip
            sits directly above the name so the tile has one bottom bar: when
            movement happened (blue), when a person was there (green), and who,
            clickable straight into the covering recording. */}
        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/85 to-transparent px-2.5 pb-2 pt-6 z-10">
          <ActivityStrip
            cameraId={camera.id}
            cameraName={camera.name}
            variant="compact"
            hours={3}
          />
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-white truncate">{camera.name}</span>
            <span className="inline-flex items-center gap-1 text-[10px] text-white/70">
              <span className={`w-1.5 h-1.5 rounded-full ${
                camera.status === "recording" ? "bg-danger" : camera.status === "live" ? "bg-green-500" : "bg-gray-400"
              } ${camera.status !== "offline" ? "pulse-dot" : ""}`} />
              {camera.status === "recording" ? "REC" : camera.status === "live" ? "LIVE" : "OFF"}
            </span>
          </div>
        </div>
      </div>

      {/* Latest activity line (hidden in wall mode to keep tiles all-feed) */}
      {!fill && latestEvent && (
        <div className="px-2.5 py-1.5 border-t border-border/50 flex items-center gap-1.5">
          <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
            latestEvent.icon === "person" ? "bg-green-500" : latestEvent.icon === "object" ? "bg-blue-400" : "bg-muted-foreground"
          }`} />
          <span className="text-[11px] text-muted-foreground truncate flex-1">{latestEvent.summary}</span>
          <span className="text-[10px] text-muted-foreground font-mono flex-shrink-0">{timeAgo(latestEvent.timestamp)}</span>
        </div>
      )}
    </div>
  );
}

// ── Add Camera Modal ──
