"use client";

import { Suspense, useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import { useWSSubscribe, useWebSocket } from "@/lib/ws";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { useWebcamPublisher, listVideoDevices } from "@/lib/webcam-publisher";
import type { StreamType } from "@/lib/camera-types";
import { AddCameraModal } from "@/components/AddCameraModal";
import { RetryCountdown } from "@/components/RetryCountdown";
import { StarredStatusRow } from "@/components/StarredStatusRow";
import { LiveCaptionOverlay } from "@/components/LiveCaptionOverlay";
import { CurrentActivityStrip } from "@/components/CurrentActivityStrip";
import { AudioActiveDot } from "@/components/AudioActiveDot";
import { VLMStatusBadge } from "@/components/VLMStatusBadge";
import { VLMOptionalBanner } from "@/components/VLMOptionalBanner";
import { SummarizeNowButton } from "@/components/SummarizeNowButton";
import { FindNowButton } from "@/components/dashboard/FindNowButton";
import { CameraStatsHover } from "@/components/CameraStatsHover";
import { RefinedBadge } from "@/components/RefinedBadge";
import { ObservationGroupCard } from "@/components/ObservationGroupCard";
import { IncidentCard } from "@/components/IncidentCard";
import { JourneyCard, type Journey } from "@/components/JourneyCard";
import { DailyDigestCard } from "@/components/DailyDigestCard";
import {
  coalesceObservations,
  isObservationGroup,
  type ObservationGroup as CoalesceGroup,
} from "@/lib/observation-grouping";
import { SystemHealthFooter } from "@/components/SystemHealthFooter";
import { PipelineDelayWidget } from "@/components/PipelineDelayWidget";
import { useWorkerHealth } from "@/lib/useWorkerHealth";
import { LLMErrorToasts } from "@/components/LLMErrorToasts";
import { OnboardingWizard } from "@/components/OnboardingWizard";
import { SetupChecklistCard } from "@/components/SetupChecklistCard";
import { AskComposerCard } from "@/components/AskComposerCard";
import { SecureAccountModal } from "@/components/SecureAccountModal";
import CameraBrandHelp from "@/components/CameraBrandHelp";
import { TranscriptCard } from "@/components/TranscriptCard";
import { SummaryCard } from "@/components/SummaryCard";
import { ConversationCard } from "@/components/ConversationCard";
import { RecordingModal } from "@/components/RecordingModal";
import { timeAgo } from "@/lib/time";

const WEBRTC_URL =
  process.env.NEXT_PUBLIC_WEBRTC_URL || "http://localhost:8889";


import type {
  ActivityEvent,
  Camera,
  ClusterSummary,
  Conversation,
  Detection,
  Digest,
  EventFilter,
  FaceDetection,
  Incident,
  Notification,
  Observation,
  Person,
  PersonActivityItem,
  PersonSummary,
  Recording,
  SearchResult,
  StatusLog,
  Summary,
  TimeRange,
  TimelineEntry,
  Transcript,
} from "./dashboard-types";

// ── Helpers ──


import {
  extractStreamName,
  formatDate,
  formatDuration,
  formatHourBucket,
  formatSize,
  formatTime,
  hourBucketKey,
  observationToEvents,
  statusColor,
  statusLabel,
  summarizeDetections,
} from "./dashboard-helpers";

import { AnalyzingShimmer, DEFAULT_FRAME_HEIGHT, DEFAULT_FRAME_WIDTH, DetectionOverlay, MiniPTZ, SignalBadge } from "@/components/dashboard/CameraOverlays";
import { CameraWall, type WallItem } from "@/components/dashboard/CameraWall";
import { WidgetTile } from "@/components/dashboard/WidgetTile";
import { WidgetBuilder } from "@/components/widgets/WidgetBuilder";
import type { Widget } from "@/components/widgets/types";
import { useConfirm } from "@/lib/feedback";

type CameraLayout = "single" | "double" | "list";
function CameraSidebarCard({
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

  // List layout. Compact horizontal row
  if (layout === "list") {
    return (
      <div
        onClick={onClick}
        className={`rounded-md border overflow-hidden cursor-pointer transition-colors group flex items-center gap-2.5 px-2.5 py-2 ${
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
          ) : isRemoteFile ? (
            <video src={camera.stream_url} autoPlay muted loop playsInline className="absolute inset-0 w-full h-full object-cover" />
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
        <button onClick={(e) => { e.stopPropagation(); window.location.href = `/cameras/${camera.id}`; }}
          className="w-5 h-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 flex-shrink-0">
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
      onClick={onClick}
      className={`rounded-lg border overflow-hidden cursor-pointer transition-colors group ${
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
        ) : isRemoteFile ? (
          <video
            src={camera.stream_url}
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
        {camera.status !== "offline" && !isRemoteFile && (
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

        {/* HAR live current-activity strip. Renders only when person_actions
            arrive (HAR enabled), so it is invisible otherwise. */}
        {camera.status !== "offline" && (
          <CurrentActivityStrip cameraId={camera.id} position="top" />
        )}

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
            className="absolute top-1.5 right-9 z-10 w-6 h-6 rounded-md bg-black/60 backdrop-blur-sm border border-white/10 flex items-center justify-center text-white/70 hover:text-white hover:bg-black/80 transition-colors opacity-0 group-hover:opacity-100"
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
            className={`absolute top-1.5 right-[4.25rem] z-10 w-6 h-6 rounded-md backdrop-blur-sm border border-white/10 flex items-center justify-center transition-colors ${
              ptzOpen ? "bg-accent text-black opacity-100" : "bg-black/60 text-white/70 hover:text-white hover:bg-black/80 opacity-0 group-hover:opacity-100"
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
          onClick={(e) => { e.stopPropagation(); window.location.href = `/cameras/${camera.id}`; }}
          className="absolute top-1.5 right-1.5 z-10 w-6 h-6 rounded-md bg-black/60 backdrop-blur-sm border border-white/10 flex items-center justify-center text-white/70 hover:text-white hover:bg-black/80 transition-colors opacity-0 group-hover:opacity-100"
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

        {/* Status + name overlay at bottom */}
        <div className="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/80 to-transparent px-2.5 pb-2 pt-6">
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



function PersonActivityModal({ personId, personName, onClose, mode = "person" }: { personId: string; personName: string; onClose: () => void; mode?: "person" | "cluster" }) {
  const { authFetch, token } = useAuth();
  const [items, setItems] = useState<PersonActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [cameraMap, setCameraMap] = useState<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const activityUrl = mode === "cluster"
          ? `/api/persons/clusters/activity/${personId}?limit=200`
          : `/api/persons/activity/${personId}?limit=200`;
        const [actRes, camRes] = await Promise.all([
          authFetch(activityUrl),
          authFetch(`/api/cameras`),
        ]);
        if (cancelled) return;
        if (actRes.ok) {
          const all: PersonActivityItem[] = await actRes.json();
          // Filter to last 24h
          const cutoff = Date.now() - 24 * 3600 * 1000;
          setItems(all.filter((i) => i.started_at && new Date(i.started_at).getTime() >= cutoff));
        }
        if (camRes.ok) {
          const cams: Camera[] = await camRes.json();
          setCameraMap(Object.fromEntries(cams.map((c) => [c.id, c.name])));
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [personId, authFetch, mode]);

  // Build per-visit sessions (gap > 10 min = new visit)
  const sessions: { start: string; end: string; cameras: Set<string>; items: PersonActivityItem[] }[] = [];
  const sortedAsc = [...items].sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime());
  const SESSION_GAP_MS = 10 * 60 * 1000;
  for (const item of sortedAsc) {
    const t = new Date(item.started_at).getTime();
    const last = sessions[sessions.length - 1];
    if (!last || t - new Date(last.end).getTime() > SESSION_GAP_MS) {
      sessions.push({ start: item.started_at, end: item.ended_at || item.started_at, cameras: new Set([item.camera_id]), items: [item] });
    } else {
      last.end = item.ended_at || item.started_at;
      last.cameras.add(item.camera_id);
      last.items.push(item);
    }
  }
  sessions.reverse(); // show most recent first

  const totalEvents = items.length;
  const totalCams = new Set(items.map((i) => i.camera_id)).size;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-2xl mx-4 rounded-xl border border-border bg-card-elevated shadow-2xl max-h-[85vh] flex flex-col overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-full overflow-hidden border border-border bg-muted flex-shrink-0">
              <img src={`/api/persons/${personId}/photo${token ? `?token=${token}` : ""}`} alt={personName} className="w-full h-full object-cover"
                onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }} />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-semibold truncate">{personName}</h2>
              <div className="text-[11px] text-muted-foreground">Activity in the last 24 hours</div>
            </div>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none">&times;</button>
        </div>

        {loading ? (
          <div className="p-8 text-center text-sm text-muted-foreground">Loading activity.</div>
        ) : sessions.length === 0 ? (
          <div className="p-8 text-center">
            <p className="text-sm text-muted-foreground">No sightings of {personName} in the last 24 hours.</p>
          </div>
        ) : (
          <div className="overflow-y-auto scrollbar-thin">
            {/* Stats strip */}
            <div className="grid grid-cols-3 gap-2 px-5 py-3 border-b border-border bg-card/30">
              <div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Visits</div>
                <div className="text-sm font-semibold">{sessions.length}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Events</div>
                <div className="text-sm font-semibold">{totalEvents}</div>
              </div>
              <div>
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider">Cameras</div>
                <div className="text-sm font-semibold">{totalCams}</div>
              </div>
            </div>

            {/* Visits / sessions */}
            <div className="p-5 space-y-4">
              {sessions.map((s, i) => {
                const start = new Date(s.start);
                const end = new Date(s.end);
                const durMin = Math.max(1, Math.round((end.getTime() - start.getTime()) / 60000));
                const camNames = Array.from(s.cameras).map((id) => cameraMap[id] || "Unknown");
                return (
                  <div key={i} className="rounded-lg border border-border bg-card/50 overflow-hidden">
                    <div className="px-3 py-2 border-b border-border/50 flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <div className="text-xs font-semibold">
                          {start.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" })}
                          {" \u2192 "}
                          {end.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                        </div>
                        <div className="text-[11px] text-muted-foreground">
                          {durMin} min \u00b7 {camNames.join(", ")}
                        </div>
                      </div>
                      <span className="text-[10px] text-muted-foreground">{s.items.length} event{s.items.length > 1 ? "s" : ""}</span>
                    </div>
                    <div className="divide-y divide-border/50">
                      {s.items.slice().reverse().map((it) => (
                        <div key={it.observation_id} className="flex gap-3 p-2.5">
                          {it.thumbnail_path ? (
                            <img src={`/api/observations/${it.observation_id}/thumbnail${token ? `?token=${token}` : ""}`} alt=""
                              className="w-20 h-14 flex-shrink-0 rounded object-cover bg-black" />
                          ) : (
                            <div className="w-20 h-14 flex-shrink-0 rounded bg-muted" />
                          )}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-start justify-between gap-2">
                              <p className="text-xs leading-snug line-clamp-2">
                                {it.vlm_description || "Motion detected"}
                              </p>
                              <span className="text-[10px] text-muted-foreground font-mono flex-shrink-0">
                                {formatTime(it.started_at)}
                              </span>
                            </div>
                            <div className="flex flex-wrap gap-1 mt-1">
                              <span className="px-1 py-0.5 text-[9px] rounded bg-muted/50 text-muted-foreground">{it.camera_name || cameraMap[it.camera_id] || "Unknown"}</span>
                              {(it.object_detections?.objects || []).slice(0, 3).map((d, di) => (
                                <span key={di} className="px-1 py-0.5 text-[9px] rounded bg-blue-900/30 text-blue-300 border border-blue-800/40">{d.label}</span>
                              ))}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}


// ── Main unified page ──

const SEARCH_HINTS = [
  "when did the cat come in",
  "person at front door",
  "show me all vehicles today",
  "who was in the backyard this morning",
  "any packages delivered",
  "was the garage door left open",
  "dog in the yard",
  "kids playing outside",
  "delivery truck in driveway",
  "someone at the gate after dark",
  "bicycle on the sidewalk",
  "how many cars passed today",
  "motion near the fence",
  "Sarah Chen arriving home",
  "any animals in the garden",
  "mail carrier",
  "lights left on in kitchen",
  "unknown person at side door",
  "show me nighttime activity",
  "cars parked in driveway",
  "when was the last delivery",
  "people walking by the house",
  "suspicious activity last night",
  "kids getting off school bus",
  "raccoon in the trash",
  "sprinkler running",
  "someone left the gate open",
  "FedEx or UPS truck",
  "how many people visited today",
  "birds on the porch",
];

function DashboardContent() {
  const { authFetch, token } = useAuth();
  const { status: wsStatus } = useWebSocket();
  const { down: workersDown, degraded: degradedComponents } = useWorkerHealth();
  const searchParams = useSearchParams();
  const initialCamera = searchParams.get("camera");
  const [searchHint, setSearchHint] = useState(() => SEARCH_HINTS[Math.floor(Math.random() * SEARCH_HINTS.length)]);

  // Camera state
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [camerasLoading, setCamerasLoading] = useState(true);
  const [learningDismissed, setLearningDismissed] = useState(true);
  useEffect(() => {
    // Default to dismissed during SSR; reveal on the client unless the user
    // closed it before (kept in localStorage so it stays gone across visits).
    try { setLearningDismissed(localStorage.getItem("nurby_learning_dismissed") === "1"); }
    catch { setLearningDismissed(false); }
  }, []);
  const [showWizard, setShowWizard] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [modalInitialType, setModalInitialType] = useState<StreamType | undefined>(undefined);
  const [activityEvents, setActivityEvents] = useState<Record<string, ActivityEvent[]>>({});
  const [selectedCamera, setSelectedCamera] = useState<string | null>(initialCamera);
  // The customizable camera wall is always the main area. The timeline /
  // activity / digest lives in a collapsible right-hand panel. Persisted so
  // the user lands with the panel where they left it.
  const [timelineOpen, setTimelineOpen] = useState<boolean>(() => {
    if (typeof window !== "undefined" && localStorage.getItem("nurby-timeline-open") === "false") return false;
    return true;
  });
  // Wraps the camera wall + the timeline panel. The wall's Fullscreen button
  // targets this so the timeline stays visible in fullscreen (see CameraWall).
  const dashboardWrapRef = useRef<HTMLDivElement>(null);
  const toggleTimeline = useCallback(() => {
    setTimelineOpen((open) => {
      const next = !open;
      try { localStorage.setItem("nurby-timeline-open", String(next)); } catch { /* ignore */ }
      return next;
    });
  }, []);
  // Dashboard widgets (custom data tiles) shown alongside cameras in the wall.
  const confirmDialog = useConfirm();
  const [widgets, setWidgets] = useState<Widget[]>([]);
  const fetchWidgets = useCallback(async () => {
    try { const res = await authFetch("/api/widgets"); if (res.ok) setWidgets(await res.json()); }
    catch { /* silent */ }
  }, [authFetch]);
  useEffect(() => { fetchWidgets(); }, [fetchWidgets]);
  const [widgetBuilder, setWidgetBuilder] = useState<{ open: boolean; editing: Widget | null }>({ open: false, editing: null });
  const deleteWidget = useCallback(async (w: Widget) => {
    if (!(await confirmDialog({ title: "Delete widget?", body: `Remove "${w.name}" from your dashboard?`, confirmLabel: "Delete", danger: true }))) return;
    try { await authFetch(`/api/widgets/${w.id}`, { method: "DELETE" }); } catch { /* ignore */ }
    fetchWidgets();
  }, [confirmDialog, fetchWidgets, authFetch]);

  // Timeline state
  const [recordings, setRecordings] = useState<Recording[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [statusLogs, setStatusLogs] = useState<StatusLog[]>([]);
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);
  const [summaries, setSummaries] = useState<Summary[]>([]);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [journeys, setJourneys] = useState<Journey[]>([]);
  const [persons, setPersons] = useState<Person[]>([]);
  const [activeEntry, setActiveEntry] = useState<string | null>(null);
  const [modalRecording, setModalRecording] = useState<Recording | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>("7d");
  const [eventFilters, setEventFilters] = useState<Set<EventFilter>>(new Set(["recordings", "observations", "status", "conversations", "summaries"]));
  // Observation coalescing window in seconds. 0 disables grouping.
  // Persisted in localStorage so the user's choice survives reload.
  const [groupWindowSeconds, setGroupWindowSeconds] = useState<number>(() => {
    if (typeof window === "undefined") return 600;
    const raw = window.localStorage.getItem("nurby-group-window-s");
    const parsed = raw != null ? parseInt(raw, 10) : NaN;
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : 600;
  });
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem("nurby-group-window-s", String(groupWindowSeconds));
  }, [groupWindowSeconds]);
  const [timelineLoading, setTimelineLoading] = useState(true);

  // Filter modal state
  const [filterModalOpen, setFilterModalOpen] = useState(false);

  // Hourly digest bucket expand state
  const [expandedBuckets, setExpandedBuckets] = useState<Set<string>>(new Set());
  // Busy hours a user has explicitly collapsed. busy hours are open by
  // default, so we track the opt-out rather than the opt-in.
  const [collapsedBuckets, setCollapsedBuckets] = useState<Set<string>>(new Set());
  // On-demand VLM recap per hour bucket. keyed by the hour-start ISO.
  const [hourSummaries, setHourSummaries] = useState<Record<string, { loading: boolean; text?: string; error?: string }>>({});

  const summarizeHour = useCallback(async (bucketKey: string) => {
    setHourSummaries((p) => ({ ...p, [bucketKey]: { loading: true } }));
    try {
      const start = new Date(bucketKey);
      const end = new Date(start.getTime() + 3600000);
      const res = await authFetch("/api/timeline/summarize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ window_start: start.toISOString(), window_end: end.toISOString() }),
      });
      if (res.ok) {
        const d = await res.json();
        setHourSummaries((p) => ({ ...p, [bucketKey]: { loading: false, text: (d.summary as string) || "Nothing notable happened in this hour." } }));
      } else {
        setHourSummaries((p) => ({ ...p, [bucketKey]: { loading: false, error: "Could not summarize this hour." } }));
      }
    } catch {
      setHourSummaries((p) => ({ ...p, [bucketKey]: { loading: false, error: "Network error." } }));
    }
  }, [authFetch]);

  // Search state
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [searchActive, setSearchActive] = useState(false);
  const [filterPerson, setFilterPerson] = useState("");
  const [filterObject, setFilterObject] = useState("");
  const [aiAnswer, setAiAnswer] = useState<string | null>(null);
  const [askingAi, setAskingAi] = useState(false);
  const [hasAiProvider, setHasAiProvider] = useState<boolean | null>(null);

  // Live events
  const [liveEvents, setLiveEvents] = useState<{ type: string; rule_name?: string; camera_id?: string; timestamp?: string; message?: string }[]>([]);
  // System-is-working strip: rule fires (event_fired) and in-flight VLM
  // analysis (vlm_status), pushed over WS the moment they happen.
  const [liveTriggers, setLiveTriggers] = useState<{
    kind: "trigger" | "vlm";
    id: string;
    label: string;
    camera: string;
    severity: string;
    ts: number;
    failed?: boolean;
  }[]>([]);
  useEffect(() => {
    // Expire strip entries: in-flight VLM chips after 90s (never got an idle
    // message), failed VLM chips after 8s (one-shot, non-alarming), trigger
    // chips after 5 minutes.
    const t = setInterval(() => {
      const now = Date.now();
      setLiveTriggers((prev) =>
        prev.filter((e) =>
          e.kind === "vlm"
            ? now - e.ts < (e.failed ? 8_000 : 90_000)
            : now - e.ts < 300_000
        )
      );
    }, 4_000);
    return () => clearInterval(t);
  }, []);
  const [wsConnected, setWsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  // Digest
  const [digest, setDigest] = useState<Digest | null>(null);
  const [digestPeriod, setDigestPeriod] = useState<"daily" | "hourly">("hourly");
  const [digestLoading, setDigestLoading] = useState(false);

  // WebSocket
  useEffect(() => {
    // The /ws socket is token-authenticated (issue #40). Skip connecting
    // until a token exists; the effect re-runs when it appears.
    if (!token) return;
    const explicit = process.env.NEXT_PUBLIC_WS_URL;
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    // Next.js rewrites do not proxy WebSocket upgrades, so same-origin /ws
    // only works when the API itself serves the page. Use the configured
    // WS endpoint (compose passes NEXT_PUBLIC_WS_URL) and fall back to
    // same-origin for setups that terminate WS at a real reverse proxy.
    const WSURL_BASE = explicit
      ? explicit.replace(/^http/, "ws").replace(/\/+$/, "")
      : `${protocol}//${window.location.host}`;
    const wsUrl = `${WSURL_BASE}/ws?token=${encodeURIComponent(token)}`;
    let reconnectTimer: ReturnType<typeof setTimeout>;

    function connect() {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      ws.onopen = () => setWsConnected(true);
      ws.onclose = () => { setWsConnected(false); reconnectTimer = setTimeout(connect, 5000); };
      ws.onerror = () => ws.close();
      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          if (data.type === "event" || data.type === "notification") {
            setLiveEvents((prev) => [data, ...prev].slice(0, 20));
            fetchTimeline();
          }
          if (data.type === "event_fired") {
            // Every rule fire lands on the live strip instantly, without
            // waiting for the 15s timeline poll.
            setLiveTriggers((prev) => [
              { kind: "trigger" as const, id: data.event_id, label: data.rule_name,
                camera: data.camera_name || "", severity: data.severity || "alert",
                ts: Date.now() },
              ...prev.filter((t) => t.id !== data.event_id),
            ].slice(0, 8));
            fetchTimeline();
          }
          if (data.type === "vlm_status" && data.camera_id) {
            const status = data.vlm?.status;
            const active = status === "queued" || status === "processing" || status === "refining";
            const failed = status === "failed";
            setLiveTriggers((prev) => {
              const others = prev.filter((t) => !(t.kind === "vlm" && t.id === data.camera_id));
              if (failed) {
                // Surface the failure briefly so it does not vanish silently.
                const reason = (data.vlm?.reason as string) || "";
                return [
                  { kind: "vlm" as const, id: data.camera_id,
                    label: reason ? `Couldn't analyze · ${reason}` : "Couldn't analyze",
                    camera: "", severity: "warn", ts: Date.now(), failed: true },
                  ...others,
                ].slice(0, 8);
              }
              if (!active) return others;
              return [
                { kind: "vlm" as const, id: data.camera_id,
                  label: status === "refining" ? "Refining description" : "AI describing scene",
                  camera: "", severity: "info", ts: Date.now() },
                ...others,
              ].slice(0, 8);
            });
          }
          if (data.type === "transcript_created") {
            fetchTimeline();
          }
          if (data.type === "summary_created") {
            fetchTimeline();
          }
          if (data.type === "conversation_updated" || data.type === "conversation_finalized") {
            fetchTimeline();
          }
          if (data.type === "vlm_refined") {
            // Cascade refiner replaced the primary description on an
            // observation. Refetch so the timeline picks up the
            // upgraded text and refined badge.
            fetchTimeline();
          }
          if (
            data.type === "incident_opened" ||
            data.type === "incident_updated" ||
            data.type === "incident_finalized"
          ) {
            // The IncidentCard already splices live state from
            // incident_updated and incident_finalized payloads. The
            // timeline refetch picks up new rows for incident_opened.
            fetchTimeline();
          }
          if (
            data.type === "journey_opened" ||
            data.type === "journey_updated" ||
            data.type === "journey_finalized"
          ) {
            fetchTimeline();
          }
        } catch { /* ignore */ }
      };
    }

    connect();
    return () => { clearTimeout(reconnectTimer); wsRef.current?.close(); };
  }, [token]); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch cameras
  const fetchCameras = useCallback(async () => {
    try {
      const res = await authFetch("/api/cameras");
      if (res.ok) setCameras(await res.json());
    } catch { /* silent */ }
    finally { setCamerasLoading(false); }
  }, []);

  const fetchActivity = useCallback(async (cameraId: string) => {
    try {
      const res = await authFetch(`/api/observations?camera_id=${cameraId}&limit=15`);
      if (res.ok) {
        const obs: Observation[] = await res.json();
        const events = obs.flatMap(observationToEvents).slice(0, 10);
        setActivityEvents((prev) => ({ ...prev, [cameraId]: events }));
      }
    } catch { /* silent */ }
  }, [authFetch]);

  const fetchPersons = useCallback(async () => {
    try {
      const res = await authFetch("/api/persons");
      if (res.ok) setPersons(await res.json());
    } catch { /* silent */ }
  }, []);

  // 24h person digest
  const [personSummaries, setPersonSummaries] = useState<PersonSummary[]>([]);
  const [clusterSummaries, setClusterSummaries] = useState<ClusterSummary[]>([]);
  const [personSummariesLoading, setPersonSummariesLoading] = useState(false);
  const [selectedPersonId, setSelectedPersonId] = useState<string | null>(null);
  const [selectedClusterId, setSelectedClusterId] = useState<string | null>(null);

  const fetchPersonSummaries = useCallback(async () => {
    setPersonSummariesLoading(true);
    try {
      const [personRes, clusterRes] = await Promise.all([
        authFetch("/api/persons/activity/summary"),
        authFetch("/api/persons/clusters/activity/summary?hours=24&min_sightings=2"),
      ]);
      if (personRes.ok) setPersonSummaries(await personRes.json());
      if (clusterRes.ok) setClusterSummaries(await clusterRes.json());
    } catch { /* silent */ }
    finally { setPersonSummariesLoading(false); }
  }, [authFetch]);

  // Fetch timeline data
  const fetchTimeline = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (selectedCamera) params.set("camera_id", selectedCamera);
      const statusParams = new URLSearchParams({ limit: "100" });
      if (selectedCamera) statusParams.set("camera_id", selectedCamera);

      const [recRes, obsRes, statusRes, notifRes, tlRes, sumRes, convRes, incRes, jourRes] = await Promise.all([
        authFetch(`/api/recordings?${params}`),
        authFetch(`/api/observations?${params}`),
        authFetch(`/api/cameras/status-logs?${statusParams}`),
        authFetch(`/api/notifications?limit=100`),
        authFetch(`/api/timeline?${params}`),
        authFetch(`/api/summaries?${params}`),
        authFetch(`/api/conversations?${params}`),
        authFetch(`/api/incidents?${params}`),
        authFetch(`/api/journeys?${params}`),
      ]);

      const now = Date.now();
      const cutoffs: Record<TimeRange, number> = { today: 86400000, "7d": 604800000, "30d": 2592000000 };
      const cutoff = now - cutoffs[timeRange];

      if (recRes.ok) setRecordings((await recRes.json()).filter((r: Recording) => new Date(r.started_at).getTime() >= cutoff));
      if (obsRes.ok) setObservations((await obsRes.json()).filter((o: Observation) => new Date(o.started_at).getTime() >= cutoff));
      if (statusRes.ok) setStatusLogs((await statusRes.json()).filter((s: StatusLog) => new Date(s.timestamp).getTime() >= cutoff));
      if (notifRes.ok) {
        const all: Notification[] = await notifRes.json();
        setNotifications(all.filter((n) => new Date(n.created_at).getTime() >= cutoff && (!selectedCamera || n.camera_id === selectedCamera)));
      }
      if (sumRes.ok) {
        const all: Summary[] = await sumRes.json();
        setSummaries(
          (Array.isArray(all) ? all : []).filter(
            (s) => new Date(s.started_at).getTime() >= cutoff
          )
        );
      }
      if (convRes.ok) {
        const all: Conversation[] = await convRes.json();
        setConversations(
          (Array.isArray(all) ? all : []).filter(
            (c) => new Date(c.started_at).getTime() >= cutoff
          )
        );
      }
      if (incRes.ok) {
        const all: Incident[] = await incRes.json();
        setIncidents(
          (Array.isArray(all) ? all : []).filter(
            (i) => new Date(i.started_at).getTime() >= cutoff
          )
        );
      }
      if (jourRes.ok) {
        const all: Journey[] = await jourRes.json();
        setJourneys(
          (Array.isArray(all) ? all : []).filter(
            (j) => new Date(j.started_at).getTime() >= cutoff
          )
        );
      }
      if (tlRes.ok) {
        const tl = await tlRes.json();
        const items: Array<Record<string, unknown>> = tl.items || [];
        const tx: Transcript[] = items
          .filter((it) => it.kind === "transcript")
          .map((it) => ({
            id: it.id as string,
            camera_id: it.camera_id as string,
            audio_capture_id: (it.audio_capture_id as string | null) ?? null,
            started_at: it.started_at as string,
            ended_at: it.ended_at as string,
            text: it.text as string,
            language: (it.language as string | null) ?? null,
            provider: it.provider as string,
          }))
          .filter((t) => new Date(t.started_at).getTime() >= cutoff);
        setTranscripts(tx);
      }
    } catch { /* silent */ }
    finally { setTimelineLoading(false); }
  }, [selectedCamera, timeRange, authFetch]);

  const fetchDigest = useCallback(async () => {
    setDigestLoading(true);
    try {
      const params = new URLSearchParams({ period: digestPeriod });
      if (selectedCamera) params.set("camera_id", selectedCamera);
      const res = await authFetch(`/api/search/digest?${params}`);
      if (res.ok) setDigest(await res.json());
    } catch { /* silent */ }
    finally { setDigestLoading(false); }
  }, [digestPeriod, selectedCamera, authFetch]);

  // Always auto-fetch digest on mount and when period/camera changes
  useEffect(() => {
    fetchDigest();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [digestPeriod, selectedCamera]);

  // Fetch person summaries for the 24h person digest
  useEffect(() => {
    if (digestPeriod === "daily") fetchPersonSummaries();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [digestPeriod]);

  // Ask the AI to synthesize an answer. Called automatically after every
  // text search so the user does not have to click a separate button.
  const askAiForQuery = useCallback(async (q: string) => {
    if (!q.trim()) return;
    setAskingAi(true);
    try {
      const res = await authFetch("/api/search/ask", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: q.trim() }) });
      if (res.ok) {
        const data = await res.json();
        const answer = data.answer || data.note || "AI could not produce an answer for this question.";
        setAiAnswer(answer);
        if (data.sources?.length > 0) setSearchResults((prev) => prev.length === 0 ? data.sources : prev);
      } else {
        setAiAnswer(`AI request failed (${res.status}). Check the server logs.`);
      }
    } catch (err) {
      setAiAnswer(`AI request failed. ${err instanceof Error ? err.message : "Unknown error"}`);
    }
    finally { setAskingAi(false); }
  }, [authFetch]);

  // Search. Runs observation search AND auto-asks the AI in parallel.
  const handleSearch = useCallback(async () => {
    if (!searchQuery.trim() && !filterPerson && !filterObject) {
      setSearchActive(false); setSearchResults([]); setAiAnswer(null); return;
    }
    setIsSearching(true); setSearchActive(true); setAiAnswer(null);
    const params = new URLSearchParams();
    if (searchQuery.trim()) params.set("q", searchQuery.trim());
    if (selectedCamera) params.set("camera_id", selectedCamera);
    if (filterPerson) params.set("person", filterPerson);
    if (filterObject) params.set("object", filterObject);

    const searchTask = (async () => {
      try {
        // Union search across observations + transcripts + conversations
        // + summaries. Each kind capped at limit_per_kind so latency
        // stays bounded. The legacy /api/search endpoint stays for
        // tools that only want observations.
        const unionParams = new URLSearchParams(params);
        unionParams.set("limit_per_kind", "10");
        const res = await authFetch(`/api/search/union?${unionParams}`);
        if (res.ok) setSearchResults((await res.json()).results);
      } catch { /* silent */ }
      finally { setIsSearching(false); }
    })();

    // Kick off AI answer in parallel. No button needed.
    const askTask = searchQuery.trim() ? askAiForQuery(searchQuery) : Promise.resolve();

    await Promise.all([searchTask, askTask]);
  }, [searchQuery, selectedCamera, filterPerson, filterObject, authFetch, askAiForQuery]);

  // Legacy handler kept for any remaining callsite. Delegates to the auto
  // path so behavior stays consistent.
  const handleAskAi = () => { askAiForQuery(searchQuery); };

  const clearSearch = () => { setSearchQuery(""); setSearchActive(false); setSearchResults([]); setAiAnswer(null); };

  const clearAllFilters = () => {
    setTimeRange("7d");
    setEventFilters(new Set(["recordings", "observations", "status", "conversations", "summaries"]));
    setFilterPerson("");
    setFilterObject("");
    setSelectedCamera(null);
  };

  const toggleEventFilter = (f: EventFilter) => {
    setEventFilters((prev) => {
      const next = new Set(prev);
      if (next.has(f)) { next.delete(f); } else { next.add(f); }
      return next;
    });
  };

  const activeFilterCount = [
    filterPerson,
    filterObject,
    timeRange !== "7d" ? "active" : "",
    eventFilters.size < 3 ? "active" : "",
  ].filter(Boolean).length;

  // Effects
  useEffect(() => {
    const i = setInterval(() => {
      setSearchHint(SEARCH_HINTS[Math.floor(Math.random() * SEARCH_HINTS.length)]);
    }, 5000);
    return () => clearInterval(i);
  }, []);
  useEffect(() => {
    authFetch("/api/providers").then(r => r.ok ? r.json() : []).then((providers: { active: boolean }[]) => {
      setHasAiProvider(providers.some(p => p.active));
    }).catch(() => setHasAiProvider(false));
  }, [authFetch]);
  useEffect(() => { fetchCameras(); fetchPersons(); }, [fetchCameras, fetchPersons]);
  useEffect(() => { const i = setInterval(fetchCameras, 10000); return () => clearInterval(i); }, [fetchCameras]);
  useEffect(() => { fetchTimeline(); const i = setInterval(fetchTimeline, 15000); return () => clearInterval(i); }, [fetchTimeline]);
  useEffect(() => { if (cameras.length > 0) cameras.forEach((cam) => { if (!activityEvents[cam.id]) fetchActivity(cam.id); }); }, [cameras]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (cameras.length === 0) return; const i = setInterval(() => cameras.forEach((c) => fetchActivity(c.id)), 15000); return () => clearInterval(i); }, [cameras, fetchActivity]);

  // First-run onboarding. Pop the wizard if no cameras exist and the
  // user has not dismissed it. Dismissal is checked both in localStorage
  // (fast path) and server-side (onboarding_dismissed) so it survives a
  // browser/device change. An admin can re-trigger the wizard by
  // flipping onboarding_dismissed back to false in Settings.
  useEffect(() => {
    if (camerasLoading) return;
    if (cameras.length > 0) return;
    let localDismissed = false;
    try {
      localDismissed = localStorage.getItem("nurby-onboarding-dismissed") === "1";
    } catch {
      localDismissed = true;
    }
    if (localDismissed) return;
    let cancelled = false;
    (async () => {
      let serverDismissed = false;
      try {
        const res = await authFetch("/api/system/settings");
        if (res.ok) {
          const data = await res.json();
          serverDismissed = !!data?.onboarding_dismissed;
        }
      } catch {
        /* fall through to showing the wizard */
      }
      if (!cancelled && !serverDismissed) setShowWizard(true);
    })();
    return () => {
      cancelled = true;
    };
  }, [camerasLoading, cameras.length, authFetch]);

  // Build timeline entries
  let entries: TimelineEntry[] = [];
  const cameraMap: Record<string, Camera> = {};
  for (const c of cameras) cameraMap[c.id] = c;

  if (searchActive) {
    entries = searchResults.map((r) => ({ id: `search-${r.id}`, type: "search_result" as const, camera_id: r.camera_id, timestamp: r.started_at, data: r }));
  } else {
    if (eventFilters.has("recordings")) entries.push(...recordings.map((r) => ({ id: `rec-${r.id}`, type: "recording" as const, camera_id: r.camera_id, timestamp: r.started_at, data: r })));
    if (eventFilters.has("observations")) {
      // Journeys take precedence over individual incidents when the
      // subject crossed multiple cameras. We push one JourneyCard per
      // multi-camera journey and suppress the underlying incidents
      // (and their observations) from the timeline so the user sees
      // one rolling story instead of N parallel cards.
      const journeyIncidentIds = new Set<string>();
      for (const j of journeys) {
        if ((j.cameras_seen_count || 0) >= 2) {
          for (const s of j.segments || []) {
            if (s.incident_id) journeyIncidentIds.add(s.incident_id);
          }
          entries.push({
            id: `jour-${j.id}`,
            type: "journey" as const,
            camera_id: j.segments?.[0]?.camera_id || "",
            timestamp: j.last_seen_at,
            data: j,
          });
        }
      }
      // Persistent incidents take precedence over the frontend-only
      // group cards. We push one IncidentCard entry per incident and
      // suppress the underlying observations from the timeline so the
      // user sees one rolling artifact per identity-on-camera.
      // Observations not linked to any incident still flow through
      // the legacy coalescer below.
      const incidentObsIds = new Set<string>();
      for (const inc of incidents) {
        if (journeyIncidentIds.has(inc.id)) {
          // Hidden — its journey card represents it.
          for (const obsId of inc.observation_ids || []) {
            incidentObsIds.add(obsId);
          }
          continue;
        }
        for (const obsId of inc.observation_ids || []) {
          incidentObsIds.add(obsId);
        }
        entries.push({
          id: `inc-${inc.id}`,
          type: "incident" as const,
          camera_id: inc.camera_id,
          timestamp: inc.last_seen_at,
          data: inc,
        });
      }
      const looseObs = observations.filter((o) => !incidentObsIds.has(o.id));
      const coalesced = coalesceObservations(
        looseObs as unknown as Parameters<typeof coalesceObservations>[0],
        groupWindowSeconds * 1000
      );
      for (const e of coalesced) {
        if (isObservationGroup(e)) {
          entries.push({
            id: e.id,
            type: "observation_group" as const,
            camera_id: e.camera_id,
            timestamp: e.latest.started_at,
            data: e,
          });
        } else {
          entries.push({
            id: `obs-${e.id}`,
            type: "observation" as const,
            camera_id: e.camera_id,
            timestamp: e.started_at,
            data: e as unknown as Observation,
          });
        }
      }
    }
    if (eventFilters.has("status")) entries.push(...statusLogs.map((s) => ({ id: `status-${s.id}`, type: "status" as const, camera_id: s.camera_id, timestamp: s.timestamp, data: s })));
    if (eventFilters.has("conversations")) entries.push(...conversations.map((c) => ({ id: `conv-${c.id}`, type: "conversation" as const, camera_id: c.camera_id, timestamp: c.ended_at_provisional, data: c })));
    if (eventFilters.has("transcripts")) entries.push(...transcripts.map((t) => ({ id: `tx-${t.id}`, type: "transcript" as const, camera_id: t.camera_id, timestamp: t.started_at, data: t })));
    if (eventFilters.has("summaries")) entries.push(...summaries.map((s) => ({ id: `sum-${s.id}`, type: "summary" as const, camera_id: s.camera_id, timestamp: s.ended_at, data: s })));
    // Always include notifications. They are explicit rule fires and deserve
    // priority in the digest even when the "status" filter is off.
    entries.push(...notifications.map((n) => ({
      id: `notif-${n.id}`,
      type: "notification" as const,
      camera_id: n.camera_id || "",
      timestamp: n.created_at,
      data: n,
    })));
  }

  entries.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

  // Group by hour bucket for digest-style view
  const hourGroups: { key: string; entries: TimelineEntry[] }[] = [];
  const hourMap: Record<string, TimelineEntry[]> = {};
  for (const e of entries) {
    const k = searchActive ? "search" : hourBucketKey(e.timestamp);
    if (!hourMap[k]) { hourMap[k] = []; hourGroups.push({ key: k, entries: hourMap[k] }); }
    hourMap[k].push(e);
  }

  // Build a lightweight digest for a bucket's entries
  // Object labels worth surfacing in a one-line summary. Everything else
  // gets folded into "and N other objects" or ignored entirely.
  const INTERESTING_OBJECTS = new Set([
    "car", "truck", "bus", "motorcycle", "bicycle", "dog", "cat",
    "package", "box", "backpack", "handbag", "knife", "gun", "fire",
  ]);

  interface BucketHighlight {
    tone: "person" | "unknown" | "plate" | "object" | "rule" | "scene";
    text: string;
    camName?: string;
    thumbnailObsId?: string;
  }

  function bucketDigest(bucketEntries: TimelineEntry[]) {
    const persons = new Set<string>();
    const personObsId: Record<string, string> = {};
    let unknownFaces = 0;
    let unknownThumb: string | undefined;
    const objectCounts: Record<string, number> = {};
    const objectCamByLabel: Record<string, string> = {};
    const plates = new Set<string>();
    const plateObsId: Record<string, string> = {};
    let recCount = 0;
    const ruleFires: { message: string; camName?: string }[] = [];
    const camHits: Record<string, number> = {};
    // Incidents and journeys are the primary timeline events. they carry a
    // VLM summary when finalized. Collect them so a busy hour is never
    // mislabeled "all quiet" just because there were no raw face rows.
    const eventHighlights: BucketHighlight[] = [];

    const humanizeSig = (kind: string, key: string): string => {
      if (kind === "person") return `${key} seen`;
      if (kind === "cluster" || kind === "unknown") return "Unrecognized person";
      if (kind === "object") return key.split(",").map((s) => s.trim()).filter(Boolean).join(" + ");
      return key || "Activity";
    };

    for (const e of bucketEntries) {
      if (e.camera_id) camHits[e.camera_id] = (camHits[e.camera_id] || 0) + 1;
      const camName = cameraMap[e.camera_id]?.name;

      if (e.type === "recording") {
        recCount++;
      } else if (e.type === "notification") {
        const n = e.data as Notification;
        ruleFires.push({ message: n.message, camName });
      } else if (e.type === "incident") {
        const inc = e.data as Incident;
        if (inc.signature_kind === "motion") continue; // ambient, not an event
        const thumb = inc.peak_observation_id || inc.thumbnails?.[0]?.obs_id || undefined;
        const occ = inc.occurrence_count > 1 ? ` (${inc.occurrence_count}×)` : "";
        const label = inc.summary_text?.trim() || `${humanizeSig(inc.signature_kind, inc.signature_key)}${occ}`;
        eventHighlights.push({
          tone: inc.signature_kind === "person" ? "person" : inc.signature_kind === "unknown" || inc.signature_kind === "cluster" ? "unknown" : "object",
          text: label,
          camName,
          thumbnailObsId: thumb,
        });
      } else if (e.type === "journey") {
        const j = e.data as Journey;
        eventHighlights.push({
          tone: "person",
          text: j.summary_text?.trim() || "Someone moved across cameras",
          camName,
        });
      } else if (e.type === "observation" || e.type === "search_result") {
        const o = e.data as Observation;
        for (const f of o.person_detections?.faces || []) {
          if (f.person_name) {
            persons.add(f.person_name);
            if (!personObsId[f.person_name]) personObsId[f.person_name] = o.id;
          } else {
            unknownFaces++;
            if (!unknownThumb) unknownThumb = o.id;
          }
        }
        for (const d of o.object_detections?.objects || []) {
          if (d.label === "license_plate") {
            if (d.plate_text) {
              plates.add(d.plate_text);
              if (!plateObsId[d.plate_text]) plateObsId[d.plate_text] = o.id;
            }
          } else if (d.label !== "person") {
            objectCounts[d.label] = (objectCounts[d.label] || 0) + 1;
            if (!objectCamByLabel[d.label] && camName) objectCamByLabel[d.label] = camName;
          }
        }
      }
    }

    const highlights: BucketHighlight[] = [];

    // Incidents/journeys first. they are the real events for the hour and
    // carry VLM summaries. Dedupe identical lines (same incident text).
    const seenEvent = new Set<string>();
    for (const h of eventHighlights) {
      if (seenEvent.has(h.text)) continue;
      seenEvent.add(h.text);
      highlights.push(h);
    }

    // Named persons are the most useful signal. List them by name.
    for (const p of persons) {
      highlights.push({ tone: "person", text: `${p} seen`, thumbnailObsId: personObsId[p] });
    }

    // Plates. Show the OCR text, not just a count.
    for (const pt of plates) {
      highlights.push({ tone: "plate", text: `Plate ${pt}`, thumbnailObsId: plateObsId[pt] });
    }

    // Unknown faces. A single row noting the count + thumbnail.
    if (unknownFaces > 0) {
      highlights.push({
        tone: "unknown",
        text: unknownFaces === 1 ? "Unknown person" : `${unknownFaces} unknown faces`,
        thumbnailObsId: unknownThumb,
      });
    }

    // Rule fires. Pull the real message so the user sees the reason.
    for (const f of ruleFires.slice(0, 3)) {
      highlights.push({ tone: "rule", text: f.message, camName: f.camName });
    }
    if (ruleFires.length > 3) {
      highlights.push({ tone: "rule", text: `${ruleFires.length - 3} more rule fires` });
    }

    // Interesting objects. Skip the long tail.
    const interesting = Object.entries(objectCounts).filter(([l]) => INTERESTING_OBJECTS.has(l));
    interesting.sort((a, b) => b[1] - a[1]);
    for (const [label, n] of interesting.slice(0, 3)) {
      highlights.push({
        tone: "object",
        text: n === 1 ? `${label} spotted` : `${n} ${label}s`,
        camName: objectCamByLabel[label],
      });
    }

    const topCams = Object.entries(camHits).sort((a, b) => b[1] - a[1]).slice(0, 2)
      .map(([id]) => cameraMap[id]?.name).filter(Boolean) as string[];

    const quiet = highlights.length === 0;

    return {
      highlights,
      quiet,
      recCount,
      total: bucketEntries.length,
      topCams,
    };
  }


  // First-run reassurance. A freshly-onboarded user lands on a dashboard
  // with cameras but no timeline yet, because the first frames take a beat
  // to process. Without this, an empty dashboard reads as broken. Shown
  // only while cameras exist, nothing has been detected, and the user has
  // not dismissed it; it disappears on its own once the first entry lands.
  const showLearningBanner =
    timelineOpen &&
    !camerasLoading &&
    cameras.length > 0 &&
    entries.length === 0 &&
    !searchActive &&
    !learningDismissed;

  // The feed tile used inside the wall: the same card the sidebar uses, in
  // fill mode so it stretches to its grid cell.
  const renderWallTile = (cam: Camera) => (
    <CameraSidebarCard
      camera={cam}
      fill
      layout="single"
      selected={false}
      onClick={() => { /* wall tiles don't drive the detail panel */ }}
      activityEvents={activityEvents[cam.id] || []}
    />
  );

  // Desktop is a viewport-locked two-column app (each column scrolls
  // internally). Below lg the columns stack, so the page must scroll
  // normally instead: no height cap, no collapsed flex children.
  return (
    <div className="px-4 py-4 lg:h-[calc(100vh-3.5rem)] lg:overflow-y-auto scrollbar-thin flex flex-col">

      <VLMOptionalBanner />

      <PipelineDelayWidget />

      {showLearningBanner && (
        <div className="mb-3 flex items-start gap-3 rounded-lg border border-accent/30 bg-accent/5 px-4 py-3">
          <svg className="animate-spin h-4 w-4 text-accent mt-0.5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <div className="flex-1 text-sm">
            <span className="font-medium">Nurby is getting to know your cameras.</span>{" "}
            <span className="text-muted-foreground">
              The first detections appear here within a minute or so as motion, faces,
              and objects are processed. You can keep setting up rules and people while it learns.
            </span>
          </div>
          <button
            type="button"
            onClick={() => {
              setLearningDismissed(true);
              try { localStorage.setItem("nurby_learning_dismissed", "1"); } catch { /* ignore */ }
            }}
            aria-label="Dismiss"
            className="text-muted-foreground hover:text-foreground text-lg leading-none flex-shrink-0"
          >
            ×
          </button>
        </div>
      )}

      {timelineOpen && (
        <>
          <div className="mb-3">
            <DailyDigestCard />
          </div>
          <StarredStatusRow />
        </>
      )}

      {widgetBuilder.open && (
        <WidgetBuilder
          widget={widgetBuilder.editing}
          onClose={() => setWidgetBuilder({ open: false, editing: null })}
          onSaved={() => { setWidgetBuilder({ open: false, editing: null }); fetchWidgets(); }}
        />
      )}

      <div ref={dashboardWrapRef} className="flex flex-col lg:flex-row gap-4 lg:flex-1 lg:min-h-[50vh] bg-background">
        {/* LEFT. Customizable camera wall (the main area). */}
        <div className="lg:flex-1 min-w-0 flex flex-col lg:min-h-0 lg:overflow-y-auto scrollbar-thin">
          {/* A stopped worker means nothing is watching, however healthy
              the cameras look. Say so loudly rather than letting the user
              read an empty timeline as a quiet day. */}
          {workersDown.length > 0 && (
            <div className="rounded-lg border border-danger/40 bg-danger/10 p-3 mb-4 flex items-start gap-2.5">
              <span className="text-danger text-sm leading-none mt-0.5">⚠</span>
              <div className="text-xs leading-relaxed">
                <span className="font-semibold text-danger">
                  {workersDown.join(" and ")} {workersDown.length > 1 ? "are" : "is"} not running.
                </span>{" "}
                <span className="text-muted-foreground">
                  Nothing is being {workersDown.includes("video ingestion") ? "recorded" : "analysed"} right
                  now, so the timeline stays empty and alerts will not fire — even
                  though your cameras may be perfectly fine. Run{" "}
                  <code className="px-1 py-0.5 rounded bg-muted font-mono">
                    docker compose up -d {workersDown.includes("video ingestion") ? "ingestion" : "perception"}
                  </code>
                  , or open{" "}
                  <Link href="/settings" className="text-accent hover:underline">
                    System doctor
                  </Link>{" "}
                  to see the full picture.
                </span>
              </div>
            </div>
          )}
          {/* Functional degradation: the worker is alive but a pipeline
              component is broken (model failed to load, writes crashing). The
              worker-down banner would never catch this, so it is called out
              separately with the specific component and reason. */}
          {workersDown.length === 0 && degradedComponents.length > 0 && (
            <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 mb-4 flex items-start gap-2.5">
              <span className="text-amber-500 text-sm leading-none mt-0.5">⚠</span>
              <div className="text-xs leading-relaxed">
                <span className="font-semibold text-amber-500">
                  {degradedComponents.map((d) => d.label).join(", ")}{" "}
                  {degradedComponents.length > 1 ? "are" : "is"} degraded.
                </span>{" "}
                <span className="text-muted-foreground">
                  The worker is running, but this part of the pipeline is failing, so
                  its results will be missing.{" "}
                  {degradedComponents[0]?.detail && (
                    <span className="text-muted-foreground/80">
                      ({degradedComponents[0].detail})
                    </span>
                  )}{" "}
                  Open{" "}
                  <Link href="/settings" className="text-accent hover:underline">
                    System doctor
                  </Link>{" "}
                  for details.
                </span>
              </div>
            </div>
          )}
          <SetupChecklistCard onAddCamera={() => { setModalInitialType(undefined); setModalOpen(true); }} />
          <AskComposerCard />
          <CameraWall
            fullscreenRef={dashboardWrapRef}
            items={[
              ...cameras.map((cam): WallItem => ({ id: cam.id, name: cam.name, render: () => renderWallTile(cam) })),
              ...widgets.map((w): WallItem => ({
                id: w.id,
                name: w.name,
                render: () => (
                  <WidgetTile
                    widget={w}
                    onEdit={(ww) => setWidgetBuilder({ open: true, editing: ww })}
                    onDelete={deleteWidget}
                  />
                ),
              })),
            ]}
            toolbarExtra={
              <>
                <button
                  onClick={() => { setModalInitialType(undefined); setModalOpen(true); }}
                  className="text-[11px] px-2 py-1 rounded border border-border text-foreground hover:bg-muted/50 transition-colors"
                  title="Connect another camera (RTSP, ONVIF, webcam)"
                >+ Camera</button>
                <button
                  onClick={() => setWidgetBuilder({ open: true, editing: null })}
                  className="text-[11px] px-2 py-1 rounded border border-border text-foreground hover:bg-muted/50 transition-colors"
                  title="Add a custom data widget"
                >+ Widget</button>
                <button
                  onClick={toggleTimeline}
                  className={`text-[11px] px-2 py-1 rounded border transition-colors flex items-center gap-1.5 ${
                    timelineOpen
                      ? "border-accent/40 bg-accent/10 text-accent-foreground"
                      : "border-border text-muted-foreground hover:text-foreground hover:bg-muted/50"
                  }`}
                  title={timelineOpen ? "Hide the timeline panel" : "Show the timeline panel"}
                  aria-pressed={timelineOpen}
                >
                  <span className={`w-1.5 h-1.5 rounded-full ${timelineOpen ? "bg-accent" : "bg-muted-foreground/40"}`} />
                  Timeline
                </button>
              </>
            }
          />
        </div>

        {/* Filter modal */}
        {filterModalOpen && (
          <div className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh]" onClick={() => setFilterModalOpen(false)}>
            <div className="fixed inset-0 bg-black/60" />
            <div className="relative w-full max-w-md rounded-xl border border-border bg-card shadow-2xl" onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between px-5 py-4 border-b border-border">
                <span className="text-sm font-medium">Filters</span>
                <div className="flex items-center gap-3">
                  {activeFilterCount > 0 && (
                    <button onClick={clearAllFilters} className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                      Clear all
                    </button>
                  )}
                  <button onClick={() => setFilterModalOpen(false)} className="text-muted-foreground hover:text-foreground transition-colors">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M18 6 6 18" /><path d="m6 6 12 12" />
                    </svg>
                  </button>
                </div>
              </div>

              <div className="p-5 space-y-5">
                {/* Time Range */}
                <div>
                  <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider block mb-2">Time Range</span>
                  <div className="flex gap-2">
                    {(["today", "7d", "30d"] as TimeRange[]).map((range) => (
                      <button key={range} onClick={() => setTimeRange(range)}
                        className={`flex-1 px-3 py-2 text-xs rounded-lg transition-colors ${timeRange === range ? "bg-accent/15 text-accent-foreground font-medium border border-accent/30" : "text-muted-foreground border border-border hover:text-foreground hover:bg-muted/50"}`}>
                        {range === "today" ? "Today" : range === "7d" ? "7 days" : "30 days"}
                      </button>
                    ))}
                  </div>
                </div>

                {/* Event Types */}
                <div>
                  <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider block mb-2">Event Types</span>
                  <div className="flex flex-col gap-1">
                    {([["recordings", "Recordings"], ["observations", "AI Observations"], ["conversations", "Conversations"], ["transcripts", "Raw Transcripts"], ["summaries", "Summaries"], ["status", "Status Changes"]] as [EventFilter, string][]).map(([value, label]) => (
                      <label key={value} className="flex items-center gap-2.5 px-3 py-2 text-xs rounded-lg hover:bg-muted/50 cursor-pointer transition-colors">
                        <input type="checkbox" checked={eventFilters.has(value)} onChange={() => toggleEventFilter(value)}
                          className="w-3.5 h-3.5 rounded border-border accent-accent" />
                        <span className={eventFilters.has(value) ? "text-foreground" : "text-muted-foreground"}>{label}</span>
                      </label>
                    ))}
                  </div>
                </div>

                {/* Observation grouping */}
                <div>
                  <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider block mb-2">Group repeats</span>
                  <p className="text-[10px] text-muted-foreground/80 mb-2 leading-relaxed">
                    Collapse repeated observations of the same person or
                    object on a camera into one rolling card.
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {([
                      { v: 0, l: "Off" },
                      { v: 300, l: "5 min" },
                      { v: 600, l: "10 min" },
                      { v: 1800, l: "30 min" },
                      { v: 3600, l: "1 hour" },
                    ] as const).map((opt) => (
                      <button
                        key={opt.v}
                        type="button"
                        onClick={() => setGroupWindowSeconds(opt.v)}
                        className={`px-2.5 py-1.5 text-xs rounded-md border transition-colors ${
                          groupWindowSeconds === opt.v
                            ? "border-accent bg-accent/10 text-accent-foreground"
                            : "border-border hover:border-muted-foreground text-muted-foreground"
                        }`}
                      >
                        {opt.l}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  {/* Person Filter */}
                  <div>
                    <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider block mb-2">Person</span>
                    <select value={filterPerson} onChange={(e) => { setFilterPerson(e.target.value); if (e.target.value) handleSearch(); }}
                      className="w-full px-3 py-2 rounded-lg bg-background border border-border text-xs focus:outline-none focus:ring-1 focus:ring-accent">
                      <option value="">Any person</option>
                      {persons.map((p) => <option key={p.id} value={p.display_name}>{p.display_name}</option>)}
                    </select>
                  </div>

                  {/* Object Filter */}
                  <div>
                    <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider block mb-2">Object</span>
                    <input type="text" value={filterObject} onChange={(e) => setFilterObject(e.target.value)}
                      onKeyDown={(e) => { if (e.key === "Enter") { handleSearch(); setFilterModalOpen(false); } }}
                      placeholder="e.g. car, dog"
                      className="w-full px-3 py-2 rounded-lg bg-background border border-border text-xs placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-accent" />
                  </div>
                </div>

                {/* Camera Filter */}
                <div>
                  <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider block mb-2">Camera</span>
                  <select value={selectedCamera || ""} onChange={(e) => setSelectedCamera(e.target.value || null)}
                    className="w-full px-3 py-2 rounded-lg bg-background border border-border text-xs focus:outline-none focus:ring-1 focus:ring-accent">
                    <option value="">All cameras</option>
                    {cameras.map((cam) => <option key={cam.id} value={cam.id}>{cam.name}</option>)}
                  </select>
                </div>
              </div>

              <div className="px-5 py-4 border-t border-border">
                <button onClick={() => { handleSearch(); setFilterModalOpen(false); }}
                  className="w-full py-2.5 text-xs font-medium rounded-lg bg-accent text-black hover:bg-accent/90 transition-colors">
                  Apply Filters
                </button>
              </div>
            </div>
          </div>
        )}

        {/* RIGHT. Timeline + Search. Collapsible side panel. */}
        <main className={`flex flex-col lg:min-h-0 min-w-0 ${timelineOpen ? "lg:w-[420px] flex-shrink-0" : "hidden"}`}>
          {/* Search bar */}
          <div className="flex-shrink-0 mb-3">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input type="text" value={searchQuery} onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); handleSearch(); } if (e.key === "Escape") clearSearch(); }}
                  placeholder={`Try "${searchHint}"`}
                  className="w-full bg-card border border-border focus:border-accent rounded-lg pl-9 pr-32 py-2.5 text-sm focus:outline-none transition-colors"
                />
                <svg className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
                </svg>
                <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                  {searchActive && <button onClick={clearSearch} className="px-1.5 py-0.5 text-[10px] rounded border border-border text-muted-foreground hover:bg-muted">Clear</button>}
                  {!isSearching && searchQuery.trim() && !searchActive && (
                    <button onClick={handleSearch} className="font-mono text-[10px] px-1.5 py-0.5 rounded bg-muted border border-border text-muted-foreground hover:bg-border">search</button>
                  )}
                </div>
              </div>
              <button onClick={() => setFilterModalOpen(true)}
                className={`relative flex-shrink-0 px-3 py-2.5 rounded-lg border transition-colors ${activeFilterCount > 0 ? "border-accent/40 bg-accent/10 text-accent-foreground" : "border-border bg-card text-muted-foreground hover:text-foreground hover:border-muted-foreground/30"}`}
                title="Filters">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
                </svg>
                {activeFilterCount > 0 && (
                  <span className="absolute -top-1.5 -right-1.5 w-4 h-4 rounded-full bg-accent text-[9px] font-bold text-black flex items-center justify-center">{activeFilterCount}</span>
                )}
              </button>
            </div>

            {searchActive && !aiAnswer && askingAi && (
              <div className="mt-2 rounded-lg border border-accent/40 bg-accent/5 p-4">
                <div className="flex items-center gap-3">
                  <div className="w-5 h-5 border-2 border-accent/30 border-t-accent rounded-full animate-spin flex-shrink-0" />
                  <div>
                    <p className="text-xs font-medium text-accent">Analyzing {searchResults.length} observation{searchResults.length !== 1 ? "s" : ""}</p>
                    <p className="text-[10px] text-muted-foreground mt-0.5">AI is reading through camera data to answer your question.</p>
                  </div>
                </div>
              </div>
            )}

            {/* AI answer fires automatically when a search runs. Only
                show the "no provider configured" hint when that's the
                case so the user knows why no answer appeared. */}
            {searchActive && !aiAnswer && !askingAi && !hasAiProvider && (
              <div className="mt-2 rounded-lg border border-border bg-card p-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-muted-foreground">
                      <path d="M12 2a4 4 0 0 1 4 4v1a2 2 0 0 1 2 2v1a4 4 0 0 1-2 3.46V16a6 6 0 0 1-12 0v-2.54A4 4 0 0 1 2 10V9a2 2 0 0 1 2-2V6a4 4 0 0 1 4-4" />
                      <circle cx="9" cy="12" r="1" /><circle cx="15" cy="12" r="1" />
                    </svg>
                    <div>
                      <p className="text-xs font-medium">AI answers unavailable</p>
                      <p className="text-[10px] text-muted-foreground">Connect an AI provider in Settings to enable natural language answers.</p>
                    </div>
                  </div>
                  <a href="/settings" className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:border-accent/50 transition-colors whitespace-nowrap">
                    Go to Settings
                  </a>
                </div>
              </div>
            )}

            {aiAnswer && (
              <div className="mt-2 rounded-lg border border-accent/40 bg-accent/5 p-3">
                <div className="flex items-center justify-between mb-1.5">
                  <div className="flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-accent pulse-dot" />
                    <span className="text-[10px] font-medium text-accent uppercase tracking-wider">AI Answer</span>
                  </div>
                  <button onClick={() => setAiAnswer(null)} className="text-[10px] text-muted-foreground hover:text-foreground">Dismiss</button>
                </div>
                <p className="text-sm leading-relaxed whitespace-pre-wrap">{aiAnswer}</p>
              </div>
            )}
          </div>

          {/* AI Digest panel. Always visible (except in search) */}
          {!searchActive && (
            <div className="rounded-xl border border-accent/30 bg-gradient-to-br from-accent/10 to-card/50 p-4 mb-3 flex-shrink-0 shadow-sm">
              <div className="flex items-center gap-3 mb-2">
                <div className="w-7 h-7 rounded-full bg-accent/20 border border-accent/40 flex items-center justify-center text-accent flex-shrink-0">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M12 2L9.1 8.6 2 9.3l5.5 4.9L5.8 22 12 18l6.2 4-1.7-7.8L22 9.3l-7.1-.7L12 2z"/>
                  </svg>
                </div>
                <span className="text-sm font-semibold flex-shrink-0">AI Digest</span>
                <div className="flex rounded-md border border-border overflow-hidden flex-shrink-0">
                  <button onClick={() => setDigestPeriod("hourly")}
                    className={`px-2 py-1 text-[10px] transition-colors ${digestPeriod === "hourly" ? "bg-accent text-black font-medium" : "text-muted-foreground hover:bg-muted"}`}>
                    1h
                  </button>
                  <button onClick={() => setDigestPeriod("daily")}
                    className={`px-2 py-1 text-[10px] border-l border-border transition-colors ${digestPeriod === "daily" ? "bg-accent text-black font-medium" : "text-muted-foreground hover:bg-muted"}`}>
                    24h
                  </button>
                </div>
                <button onClick={fetchDigest} disabled={digestLoading}
                  title="Regenerate digest"
                  className="p-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-50 flex-shrink-0">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={digestLoading ? "animate-spin" : ""}>
                    <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>
                  </svg>
                </button>
                <span className="text-[10px] text-muted-foreground truncate ml-auto">
                  {selectedCamera && cameraMap[selectedCamera] ? cameraMap[selectedCamera].name : "All Cameras"}
                </span>
              </div>

              {digestLoading && !digest ? (
                <div className="space-y-1.5 animate-pulse">
                  <div className="h-2.5 w-5/6 rounded bg-muted/70" />
                  <div className="h-2.5 w-4/6 rounded bg-muted/70" />
                  <div className="h-2.5 w-3/6 rounded bg-muted/50" />
                </div>
              ) : digest && digest.total_observations > 0 ? (
                <>
                  <p className="text-xs leading-relaxed">{digest.summary}</p>
                  {digest.highlights.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {digest.highlights.slice(0, 4).map((h, i) => (
                        <span key={i} className="px-2 py-0.5 text-[10px] rounded-full bg-background/60 border border-border text-muted-foreground">{h}</span>
                      ))}
                    </div>
                  )}
                  <div className="mt-2 flex items-center justify-end text-[10px] text-muted-foreground">
                    <span className="font-mono">{digest.period_label}</span>
                  </div>

                  {/* 24h person gallery */}
                  {digestPeriod === "daily" && (
                    <div className="mt-3 pt-3 border-t border-border/50">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">People seen today</span>
                        {personSummariesLoading && <span className="text-[10px] text-muted-foreground">loading.</span>}
                      </div>
                      {(() => {
                        const seen = personSummaries.filter((p) => p.sightings_24h > 0);
                        const unknowns = clusterSummaries.filter((c) => c.sightings_24h > 0);
                        if (seen.length === 0 && unknowns.length === 0 && !personSummariesLoading) {
                          return <p className="text-[11px] text-muted-foreground">No faces recognized or grouped in the last 24 hours.</p>;
                        }
                        return (
                          <div className="flex gap-2 overflow-x-auto scrollbar-thin pb-1">
                            {seen.map((p) => (
                              <button key={p.person_id} onClick={() => setSelectedPersonId(p.person_id)}
                                className="flex-shrink-0 w-20 text-center group">
                                <div className="w-16 h-16 mx-auto rounded-full overflow-hidden border-2 border-border group-hover:border-accent transition-colors bg-muted">
                                  {p.photo_path ? (
                                    <img src={`/api/persons/${p.person_id}/photo${token ? `?token=${token}` : ""}`} alt={p.display_name} className="w-full h-full object-cover" />
                                  ) : (
                                    <div className="w-full h-full flex items-center justify-center text-sm font-semibold text-muted-foreground">
                                      {p.display_name.charAt(0).toUpperCase()}
                                    </div>
                                  )}
                                </div>
                                <div className="mt-1 text-[11px] font-medium truncate">{p.display_name}</div>
                                <div className="text-[9px] text-muted-foreground">{p.sightings_24h} visit{p.sightings_24h > 1 ? "s" : ""}</div>
                              </button>
                            ))}
                            {unknowns.map((c) => (
                              <button key={c.cluster_id} onClick={() => setSelectedClusterId(c.cluster_id)}
                                className="flex-shrink-0 w-20 text-center group" title={c.appearance_description || ""}>
                                <div className="w-16 h-16 mx-auto rounded-full overflow-hidden border-2 border-dashed border-amber-500/50 group-hover:border-amber-400 transition-colors bg-muted">
                                  {c.sample_thumbnail_path ? (
                                    <img src={`/api/persons/suggestions/${c.cluster_id}/thumbnail${token ? `?token=${token}` : ""}`} alt={c.auto_label} className="w-full h-full object-cover" />
                                  ) : (
                                    <div className="w-full h-full flex items-center justify-center text-xs font-semibold text-amber-400/80">?</div>
                                  )}
                                </div>
                                <div className="mt-1 text-[11px] font-medium truncate text-amber-300/90">{c.auto_label}</div>
                                <div className="text-[9px] text-muted-foreground truncate">
                                  {c.appearance_description || (c.appearance_description_status === "pending" ? "describing." : `${c.sightings_24h} visit${c.sightings_24h > 1 ? "s" : ""}`)}
                                </div>
                              </button>
                            ))}
                          </div>
                        );
                      })()}
                    </div>
                  )}
                </>
              ) : (
                <div className="text-xs text-muted-foreground leading-relaxed">
                  {cameras.length === 0
                    ? "Connect a camera to start generating activity summaries."
                    : digestPeriod === "hourly"
                      ? "No activity in the last hour. The digest will appear as soon as events are observed."
                      : "No activity in the last 24 hours. Try adjusting cameras or check back later."}
                </div>
              )}
            </div>
          )}

          {/* Live event toasts */}
          {!searchActive && (liveEvents.length > 0 || liveTriggers.length > 0) && (
            <div className="mb-3 space-y-1 flex-shrink-0">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-medium text-accent uppercase tracking-wider flex items-center gap-1">
                  {/* Dot mirrors relay health so a paused strip doesn't keep
                      pulsing "live" while the WS is actually down. */}
                  <span
                    className={`w-1.5 h-1.5 rounded-full pulse-dot ${
                      wsStatus === "connected"
                        ? "bg-accent"
                        : wsStatus === "disconnected"
                          ? "bg-red-500"
                          : "bg-yellow-500"
                    }`}
                  />
                  Live
                  {wsStatus !== "connected" && (
                    <span className="text-muted-foreground normal-case font-normal tracking-normal">
                      · {wsStatus === "disconnected" ? "paused" : "reconnecting…"}
                    </span>
                  )}
                </span>
                <button onClick={() => { setLiveEvents([]); setLiveTriggers([]); }} className="text-[10px] text-muted-foreground hover:text-foreground">clear</button>
              </div>
              {liveTriggers.filter((t) => t.kind === "vlm").slice(0, 2).map((t) => (
                <div key={`vlm-${t.id}`}
                  className={`px-3 py-1.5 rounded-md border text-xs flex items-center gap-2 ${
                    t.failed
                      ? "border-rose-500/30 bg-rose-500/5"
                      : "border-violet-500/30 bg-violet-500/5"
                  }`}>
                  {t.failed ? (
                    <svg className="h-3 w-3 text-rose-400 flex-shrink-0" viewBox="0 0 24 24" fill="none"
                      stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10" />
                      <line x1="12" y1="8" x2="12" y2="12" />
                      <line x1="12" y1="16" x2="12.01" y2="16" />
                    </svg>
                  ) : (
                    <svg className="animate-spin h-3 w-3 text-violet-400 flex-shrink-0" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                  )}
                  <span className={t.failed ? "text-rose-300" : "text-violet-300"}>{t.label}</span>
                  <span className="ml-auto text-[10px] text-muted-foreground">
                    {cameras.find((c) => c.id === t.id)?.name || ""}
                  </span>
                </div>
              ))}
              {liveTriggers.filter((t) => t.kind === "trigger").slice(0, 3).map((t) => (
                <Link href="/events" key={`trig-${t.id}`}
                  className={`px-3 py-1.5 rounded-md border text-xs flex items-center gap-2 transition-colors ${
                    t.severity === "alert"
                      ? "border-red-500/30 bg-red-500/5 hover:bg-red-500/10"
                      : "border-border bg-muted/20 hover:bg-muted/40"
                  }`}>
                  <span className={t.severity === "alert" ? "text-red-400" : "text-muted-foreground"}>⚡</span>
                  <span>Rule fired · {t.label}</span>
                  {t.camera && <span className="text-[10px] text-muted-foreground">{t.camera}</span>}
                  <span className="ml-auto text-[10px] text-muted-foreground font-mono">
                    {new Date(t.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                  </span>
                </Link>
              ))}
              {liveEvents.slice(0, 3).map((evt, i) => (
                <div key={i} className="px-3 py-1.5 rounded-md border border-accent/30 bg-accent/5 text-xs flex items-center justify-between">
                  <span>{evt.message || `Rule "${evt.rule_name}" fired`}</span>
                  <span className="text-[10px] text-muted-foreground font-mono">{evt.timestamp ? formatTime(evt.timestamp) : "now"}</span>
                </div>
              ))}
            </div>
          )}

          {/* Timeline feed. Internal scroll on desktop; on mobile the
              column isn't height-capped, so bound it to keep the page
              from growing endlessly. */}
          <div className="flex-1 max-h-[60vh] lg:max-h-none overflow-y-auto scrollbar-thin pr-1">
            {isSearching ? (
              <div className="flex flex-col items-center justify-center py-20 gap-3">
                <svg className="animate-spin h-5 w-5 text-muted-foreground" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
                <div className="text-xs text-muted-foreground">Searching observations.</div>
              </div>
            ) : timelineLoading && entries.length === 0 ? (
              <div className="space-y-3">
                {[0, 1, 2].map((i) => (
                  <div key={i} className="rounded-lg border border-border bg-card/30 p-3 animate-pulse">
                    <div className="flex items-center justify-between mb-2">
                      <div className="h-3 w-32 rounded bg-muted" />
                      <div className="h-3 w-16 rounded bg-muted" />
                    </div>
                    <div className="h-2.5 w-4/5 rounded bg-muted/70 mb-1.5" />
                    <div className="h-2.5 w-2/3 rounded bg-muted/70" />
                  </div>
                ))}
              </div>
            ) : entries.length === 0 ? (
              cameras.length === 0 ? (
                <div className="rounded-xl border border-dashed border-border bg-card/30 p-8 text-center">
                  <div className="w-12 h-12 rounded-full bg-accent/10 border border-accent/30 flex items-center justify-center mx-auto mb-3 text-accent">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>
                    </svg>
                  </div>
                  <h3 className="text-sm font-semibold mb-1">Connect your first camera</h3>
                  <p className="text-xs text-muted-foreground max-w-sm mx-auto mb-4 leading-relaxed">
                    The timeline fills in as motion, faces, and objects are detected. Add any RTSP feed, discover ONVIF cameras on your network, or use this device as a test source.
                  </p>
                  <div className="flex items-center justify-center gap-2">
                    <button onClick={async () => {
                      try { const r = await authFetch("/api/cameras/demo", { method: "POST" }); if (r.ok) fetchCameras(); } catch { /* silent */ }
                    }}
                      className="px-3 py-1.5 text-xs rounded-md bg-accent text-accent-foreground font-medium hover:opacity-90"
                      title="No camera? Stream looping sample footage to try Nurby.">
                      Try a demo camera
                    </button>
                    <button onClick={() => { setModalInitialType(undefined); setModalOpen(true); }}
                      className="px-3 py-1.5 text-xs rounded-md bg-foreground text-background font-medium hover:opacity-90">
                      Add a camera
                    </button>
                    <button onClick={() => { setModalInitialType("usb"); setModalOpen(true); }}
                      className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted">
                      Use webcam
                    </button>
                  </div>
                </div>
              ) : searchActive ? (
                <div className="rounded-xl border border-dashed border-border bg-card/30 p-8 text-center">
                  <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center mx-auto mb-3 text-muted-foreground">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>
                    </svg>
                  </div>
                  <h3 className="text-sm font-semibold mb-1">No matches</h3>
                  <p className="text-xs text-muted-foreground max-w-sm mx-auto mb-4">
                    Nothing matched {searchQuery.trim() ? <>&ldquo;<span className="font-medium text-foreground">{searchQuery.trim()}</span>&rdquo;</> : "these filters"}. Try broadening the time range or removing filters.
                  </p>
                  <button onClick={clearAllFilters}
                    className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted">
                    Clear filters
                  </button>
                </div>
              ) : (
                <div className="rounded-xl border border-dashed border-border bg-card/30 p-8 text-center">
                  <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center mx-auto mb-3 text-muted-foreground">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                    </svg>
                  </div>
                  <h3 className="text-sm font-semibold mb-1">
                    {workersDown.length > 0 ? "Nothing is running" : "Nothing happened yet"}
                  </h3>
                  <p className="text-xs text-muted-foreground max-w-sm mx-auto mb-4 leading-relaxed">
                    {/* Worker state first: while a worker is down every camera
                        looks broken, and telling the user to check stream URLs
                        and credentials sends them to debug hardware that is
                        fine. Only blame the camera once we know something is
                        actually watching it. */}
                    {workersDown.length > 0
                      ? `This is not a quiet day: ${workersDown.join(" and ")} ${
                          workersDown.length > 1 ? "are" : "is"
                        } not running, so nothing can be detected. Your cameras may be fine.`
                      : cameras.some((c) => c.status === "offline")
                      ? "Some cameras are offline. Check their stream URLs or credentials."
                      : "Cameras are connected and watching. Events will appear here as soon as something moves."}
                  </p>
                  <div className="flex items-center justify-center gap-2 flex-wrap">
                    {activeFilterCount > 0 && (
                      <button onClick={clearAllFilters}
                        className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted">
                        Clear filters ({activeFilterCount})
                      </button>
                    )}
                    <button onClick={() => setTimeRange("30d")}
                      className="px-3 py-1.5 text-xs rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted">
                      Try last 30 days
                    </button>
                  </div>
                </div>
              )
            ) : (
              <div className="space-y-3">
                {hourGroups.map(({ key: bucketKey, entries: dateEntries }) => {
                  const d = searchActive ? null : bucketDigest(dateEntries);
                  // Hours with real activity are expanded by default. the
                  // timeline should show, not hide behind a "peek". Quiet
                  // hours stay collapsed and peekable. A user can still
                  // collapse a busy hour, tracked in collapsedBuckets.
                  const isExpanded =
                    searchActive ||
                    expandedBuckets.has(bucketKey) ||
                    (!!d && !d.quiet && !collapsedBuckets.has(bucketKey));
                  return (
                  <div key={bucketKey}>
                    {!searchActive && d && d.quiet && (
                      <button
                        onClick={() => {
                          setExpandedBuckets((prev) => {
                            const next = new Set(prev);
                            if (next.has(bucketKey)) next.delete(bucketKey); else next.add(bucketKey);
                            return next;
                          });
                        }}
                        className="w-full text-left flex items-center gap-2 px-2 py-1 mb-0.5 rounded hover:bg-muted/40 transition-colors"
                      >
                        <span className="w-1 h-1 rounded-full bg-muted-foreground/40" />
                        <span className="text-[11px] text-muted-foreground font-medium">{formatHourBucket(bucketKey)}</span>
                        <span className="text-[11px] text-muted-foreground/70 italic">all quiet</span>
                        {d.recCount > 0 && (
                          <span className="text-[10px] text-muted-foreground/70">· {d.recCount} rec</span>
                        )}
                        <span className="ml-auto text-[10px] text-muted-foreground/60">{isExpanded ? "hide" : "peek"}</span>
                      </button>
                    )}
                    {!searchActive && d && !d.quiet && (
                      <button
                        onClick={() => {
                          setCollapsedBuckets((prev) => {
                            const next = new Set(prev);
                            // isExpanded true means open. clicking collapses,
                            // so add to collapsedBuckets (and clear any
                            // explicit expand).
                            if (isExpanded) next.add(bucketKey); else next.delete(bucketKey);
                            return next;
                          });
                          setExpandedBuckets((prev) => {
                            if (!prev.has(bucketKey)) return prev;
                            const next = new Set(prev); next.delete(bucketKey); return next;
                          });
                        }}
                        className={`w-full text-left rounded-lg border p-3 mb-1.5 transition-colors ${isExpanded ? "border-accent/50 bg-card" : "border-border bg-card/50 hover:border-accent/40 hover:bg-card"}`}
                      >
                        <div className="flex items-start justify-between gap-3 mb-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="text-xs font-semibold">{formatHourBucket(bucketKey)}</span>
                            {d.topCams.length > 0 && (
                              <span className="text-[10px] text-muted-foreground truncate">{d.topCams.join(", ")}</span>
                            )}
                          </div>
                          <span className="text-[10px] text-muted-foreground flex-shrink-0">{isExpanded ? "\u25BC hide" : "\u25B6 show"}</span>
                        </div>
                        <ul className="space-y-1">
                          {d.highlights.slice(0, 5).map((h, i) => {
                            const toneClass = h.tone === "person" ? "text-green-400"
                              : h.tone === "unknown" ? "text-yellow-400"
                              : h.tone === "plate" ? "text-accent"
                              : h.tone === "rule" ? "text-blue-400"
                              : "text-foreground";
                            return (
                              <li key={i} className="flex items-center gap-2 text-xs">
                                {h.thumbnailObsId ? (
                                  <img src={`/api/observations/${h.thumbnailObsId}/thumbnail${token ? `?token=${token}` : ""}`} alt="" className="w-8 h-6 rounded object-cover bg-muted flex-shrink-0" />
                                ) : (
                                  <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${h.tone === "rule" ? "bg-blue-400" : h.tone === "plate" ? "bg-accent" : h.tone === "person" ? "bg-green-400" : h.tone === "unknown" ? "bg-yellow-400" : "bg-muted-foreground"}`} />
                                )}
                                <span className={`${toneClass} truncate`}>{h.text}</span>
                                {h.camName && (
                                  <span className="text-[10px] text-muted-foreground truncate">on {h.camName}</span>
                                )}
                              </li>
                            );
                          })}
                          {d.highlights.length > 5 && (
                            <li className="text-[10px] text-muted-foreground pl-3.5">and {d.highlights.length - 5} more</li>
                          )}
                        </ul>
                      </button>
                    )}
                    {searchActive && (
                      <div className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2 sticky top-0 bg-background/80 backdrop-blur-sm py-1 z-10">Search Results</div>
                    )}
                    {isExpanded && (
                    <div className="space-y-1.5 pl-2 border-l border-border/50">
                      {!searchActive && (() => {
                        const hs = hourSummaries[bucketKey];
                        if (hs?.text) return (
                          <p className="text-[11px] text-amber-200/90 bg-amber-500/[0.06] border border-amber-500/20 rounded-md px-2.5 py-1.5 leading-snug mb-1">
                            <span className="opacity-70">✨ </span>{hs.text}
                          </p>
                        );
                        if (hs?.error) return <div className="text-[11px] text-red-400 mb-1">{hs.error}</div>;
                        return (
                          <button
                            onClick={() => summarizeHour(bucketKey)}
                            disabled={hs?.loading}
                            className="text-[11px] text-accent hover:underline disabled:opacity-50 mb-1"
                          >
                            {hs?.loading ? "Summarizing this hour." : "✨ Summarize this hour"}
                          </button>
                        );
                      })()}
                      {dateEntries.map((entry) => {
                        const cam = cameraMap[entry.camera_id];
                        const isActive = activeEntry === entry.id;

                        if (entry.type === "notification") {
                          const n = entry.data as Notification;
                          const tone = n.severity === "critical" ? "text-danger"
                            : n.severity === "warning" ? "text-warning"
                            : "text-blue-400";
                          return (
                            <div key={entry.id} className="px-3 py-2 rounded-lg border border-border/50 flex items-start gap-2">
                              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className={`${tone} flex-shrink-0 mt-0.5`}>
                                <path d="M18 8A6 6 0 006 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 01-3.46 0" />
                              </svg>
                              <div className="flex-1 min-w-0">
                                <p className="text-xs"><span className={`${tone} font-medium`}>Rule fired</span> · {n.message}</p>
                                {cam?.name && <p className="text-[10px] text-muted-foreground mt-0.5">{cam.name}</p>}
                              </div>
                              <span className="text-[10px] text-muted-foreground font-mono flex-shrink-0">{formatTime(n.created_at)}</span>
                            </div>
                          );
                        }

                        if (entry.type === "search_result") {
                          const r = entry.data as SearchResult;
                          // Branch on union-search discriminator. Non-
                          // observation kinds render as simpler cards
                          // tinted by their type.
                          if (r.kind === "transcript") {
                            return (
                              <div
                                key={entry.id}
                                className="rounded-lg border border-emerald-700/30 bg-emerald-950/15 p-3"
                              >
                                <div className="flex items-center gap-2 text-[10px] text-emerald-300 uppercase tracking-wider mb-1">
                                  <span>Transcript</span>
                                  <span className="text-muted-foreground">·</span>
                                  <span className="text-muted-foreground">{r.camera_name || cam?.name || "Camera"}</span>
                                  <span className="ml-auto font-mono text-muted-foreground">{formatTime(r.started_at)}</span>
                                </div>
                                <p className="text-xs italic text-zinc-100 leading-relaxed">{r.text || ""}</p>
                              </div>
                            );
                          }
                          if (r.kind === "conversation") {
                            return (
                              <div
                                key={entry.id}
                                className="rounded-lg border border-emerald-700/40 bg-emerald-950/20 p-3"
                              >
                                <div className="flex items-center gap-2 text-[10px] text-emerald-300 uppercase tracking-wider mb-1">
                                  <span>Conversation</span>
                                  <span className="text-muted-foreground">·</span>
                                  <span className="text-muted-foreground">{r.camera_name || cam?.name || "Camera"}</span>
                                  {r.transcript_count != null && (
                                    <span className="text-muted-foreground">· {r.transcript_count} msg</span>
                                  )}
                                  <span className="ml-auto font-mono text-muted-foreground">{formatTime(r.started_at)}</span>
                                </div>
                                <p className="text-xs leading-relaxed text-foreground">{r.summary_text || "(no summary)"}</p>
                              </div>
                            );
                          }
                          if (r.kind === "summary") {
                            return (
                              <div
                                key={entry.id}
                                className="rounded-lg border border-indigo-500/40 bg-indigo-500/5 p-3"
                              >
                                <div className="flex items-center gap-2 text-[10px] text-indigo-300 uppercase tracking-wider mb-1">
                                  <span>{r.summary_kind === "event" ? "Event recap" : "Recap"}</span>
                                  <span className="text-muted-foreground">·</span>
                                  <span className="text-muted-foreground">{r.camera_name || cam?.name || "Camera"}</span>
                                  <span className="ml-auto font-mono text-muted-foreground">{formatTime(r.started_at)}</span>
                                </div>
                                <p className="text-xs leading-relaxed text-foreground">{r.summary_text || ""}</p>
                              </div>
                            );
                          }
                          // Default: observation shape.
                          const srFaces = r.person_detections?.faces || [];
                          const srNamed = srFaces.filter((f) => f.person_name);
                          const srUnknown = srFaces.filter((f) => !f.person_name);
                          const srObjects = r.object_detections?.objects?.filter((d) => d.label !== "person" && d.label !== "license_plate") || [];
                          const srPlates = r.object_detections?.objects?.filter((d) => d.label === "license_plate" && d.plate_text) || [];
                          return (
                            <div key={entry.id}>
                              <button onClick={() => setActiveEntry(isActive ? null : entry.id)}
                                className={`w-full text-left rounded-lg border transition-colors overflow-hidden ${isActive ? "border-accent bg-card" : "border-border hover:border-accent/50 hover:bg-card/50"}`}>
                                <div className="flex gap-3">
                                  {r.thumbnail_path && (
                                    <div className="w-20 h-16 flex-shrink-0 bg-black/50 overflow-hidden">
                                      <img src={`/api/observations/${r.id}/thumbnail${token ? `?token=${token}` : ""}`} alt="" className="w-full h-full object-cover" />
                                    </div>
                                  )}
                                  <div className={`flex-1 min-w-0 py-2 ${r.thumbnail_path ? "pr-3" : "px-3"}`}>
                                    <div className="flex items-start justify-between gap-2">
                                      <div className="min-w-0 flex-1">
                                        {srFaces.length > 0 ? (
                                          <div className="flex flex-wrap items-center gap-1">
                                            {srNamed.map((f, i) => <span key={`n${i}`} className="text-xs font-medium text-green-400">{f.person_name}</span>)}
                                            {srNamed.length > 0 && srUnknown.length > 0 && <span className="text-[10px] text-muted-foreground">+</span>}
                                            {srUnknown.length > 0 && <span className="text-xs text-yellow-400">{srUnknown.length === 1 ? "Unknown person" : `${srUnknown.length} unknown`}</span>}
                                          </div>
                                        ) : (
                                          <p className="text-xs font-medium line-clamp-1">
                                            {r.vlm_description ? r.vlm_description.split(/\.\s/)[0].slice(0, 80) : "Motion detected"}
                                          </p>
                                        )}
                                        <div className="flex flex-wrap items-center gap-1 mt-1">
                                          {srObjects.slice(0, 4).map((obj, i) => (
                                            <span key={i} className="px-1 py-0.5 text-[9px] rounded bg-blue-900/30 text-blue-300 border border-blue-800/40">{obj.label}</span>
                                          ))}
                                          {srPlates.map((d, i) => (
                                            <span key={`p${i}`} className="px-1 py-0.5 text-[9px] rounded bg-accent/20 text-accent border border-accent/40">{d.plate_text}</span>
                                          ))}
                                          <span className="px-1 py-0.5 text-[9px] rounded bg-muted/50 text-muted-foreground">{r.camera_name || cam?.name || "Unknown"}</span>
                                        </div>
                                      </div>
                                      <span className="text-[10px] text-muted-foreground font-mono flex-shrink-0 pt-0.5">{formatTime(r.started_at)}</span>
                                    </div>
                                  </div>
                                </div>
                              </button>
                              {isActive && (
                                <div className="mt-1.5 rounded-lg border border-border bg-card p-3 space-y-2">
                                  {r.thumbnail_path && (
                                    <div className="rounded-lg overflow-hidden border border-border">
                                      <img src={`/api/observations/${r.id}/thumbnail${token ? `?token=${token}` : ""}`} alt="" className="w-full" />
                                    </div>
                                  )}
                                  {r.vlm_description && <p className="text-xs leading-relaxed">{r.vlm_description}</p>}
                                </div>
                              )}
                            </div>
                          );
                        }

                        if (entry.type === "status") {
                          const log = entry.data as StatusLog;
                          const isOnline = log.status === "live" || log.status === "recording";
                          // Match recording status log to nearest Recording (same cam, within 30s)
                          let matchedRec: Recording | null = null;
                          if (log.status === "recording") {
                            const logTs = new Date(log.timestamp).getTime();
                            let best = Infinity;
                            for (const r of recordings) {
                              if (r.camera_id !== log.camera_id) continue;
                              const d = Math.abs(new Date(r.started_at).getTime() - logTs);
                              if (d < best && d <= 30000) { best = d; matchedRec = r; }
                            }
                          }
                          const row = (
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <div className={`w-1.5 h-1.5 rounded-full ${statusColor(log.status)}`} />
                                <span className="text-xs"><span className="font-medium">{cam?.name || "Unknown"}</span><span className="mx-1 text-muted-foreground">{log.status === "recording" ? "started" : log.status === "offline" ? "went" : "is"}</span><span className={isOnline ? "text-green-400" : "text-muted-foreground"}>{log.status === "recording" ? "recording" : statusLabel(log.status).toLowerCase()}</span></span>
                              </div>
                              <span className="text-[10px] text-muted-foreground font-mono">{formatTime(log.timestamp)}</span>
                            </div>
                          );
                          if (!matchedRec) {
                            return (
                              <div key={entry.id} className="px-3 py-2 rounded-lg border border-border/50">
                                {row}
                              </div>
                            );
                          }
                          const rec = matchedRec;
                          return (
                            <div key={entry.id}>
                              <button onClick={() => setModalRecording(rec)}
                                className="w-full text-left px-3 py-2 rounded-lg border border-border/50 hover:border-accent/50 hover:bg-card/50 transition-colors">
                                {row}
                              </button>
                            </div>
                          );
                        }

                        if (entry.type === "conversation") {
                          const c = entry.data as Conversation;
                          return (
                            <ConversationCard
                              key={entry.id}
                              id={c.id}
                              cameraId={c.camera_id}
                              cameraName={cam?.name}
                              startedAt={c.started_at}
                              endedAtProvisional={c.ended_at_provisional}
                              endedAt={c.ended_at}
                              finalized={c.finalized}
                              transcriptCount={c.transcript_count}
                              summaryText={c.summary_text}
                              cleanedText={c.cleaned_text}
                              summaryProviderName={c.summary_provider_name}
                              hasClip={c.has_clip}
                            />
                          );
                        }

                        if (entry.type === "summary") {
                          const s = entry.data as Summary;
                          return (
                            <SummaryCard
                              key={entry.id}
                              id={s.id}
                              cameraId={s.camera_id}
                              cameraName={cam?.name}
                              kind={s.kind}
                              startedAt={s.started_at}
                              endedAt={s.ended_at}
                              providerName={s.provider_name}
                              triggerReason={s.trigger_reason}
                              summaryText={s.summary_text}
                              peopleSeen={s.people_seen}
                              platesSeen={s.plates_seen}
                              objectCounts={s.object_counts}
                            />
                          );
                        }

                        if (entry.type === "transcript") {
                          const tx = entry.data as Transcript;
                          return (
                            <TranscriptCard
                              key={entry.id}
                              id={tx.id}
                              cameraId={tx.camera_id}
                              cameraName={cam?.name}
                              startedAt={tx.started_at}
                              endedAt={tx.ended_at}
                              text={tx.text}
                              audioCaptureId={tx.audio_capture_id}
                              language={tx.language}
                              provider={tx.provider}
                            />
                          );
                        }

                        if (entry.type === "recording") {
                          const rec = entry.data as Recording;
                          return (
                            <div key={entry.id}>
                              <button onClick={() => setModalRecording(rec)}
                                className="w-full text-left px-3 py-2.5 rounded-lg border border-border hover:border-accent/50 hover:bg-card/50 transition-colors">
                                <div className="flex items-center justify-between">
                                  <div className="flex items-center gap-2">
                                    <div className="w-1.5 h-1.5 rounded-full bg-blue-500" />
                                    <div>
                                      <div className="text-xs font-medium">
                                        Recording
                                        <span className="ml-1.5 font-normal text-muted-foreground">{formatDuration(rec.duration_seconds)}</span>
                                        {rec.file_size_bytes && <span className="ml-1 font-normal text-muted-foreground">{formatSize(rec.file_size_bytes)}</span>}
                                      </div>
                                      <div className="flex items-center gap-1 mt-0.5">
                                        <span className="px-1 py-0.5 text-[9px] rounded bg-muted/50 text-muted-foreground">{cam?.name || "Unknown"}</span>
                                        <span className="font-mono text-[10px] text-muted-foreground">{formatTime(rec.started_at)}{rec.ended_at && ` \u2192 ${formatTime(rec.ended_at)}`}</span>
                                      </div>
                                    </div>
                                  </div>
                                </div>
                              </button>
                            </div>
                          );
                        }

                        if (entry.type === "journey") {
                          const j = entry.data as Journey;
                          return <JourneyCard key={entry.id} journey={j} />;
                        }

                        if (entry.type === "incident") {
                          const inc = entry.data as Incident;
                          return (
                            <IncidentCard
                              key={entry.id}
                              incident={inc}
                              cameraName={cam?.name}
                            />
                          );
                        }

                        if (entry.type === "observation_group") {
                          const g = entry.data as CoalesceGroup;
                          const idLookup = new Map<string, Observation>(
                            g.observations.map((o) => [o.id, o as unknown as Observation])
                          );
                          return (
                            <ObservationGroupCard
                              key={entry.id}
                              group={g}
                              cameraName={cam?.name}
                              renderObservation={(obsId) => {
                                const o = idLookup.get(obsId);
                                if (!o) return null;
                                return (
                                  <div className="rounded border border-border/60 bg-card/40 p-2 text-xs">
                                    <div className="flex items-center gap-2 text-[10px] text-muted-foreground mb-1">
                                      <span className="font-mono">
                                        {new Date(o.started_at).toLocaleTimeString()}
                                      </span>
                                      {o.refined_by_provider_name && (
                                        <span className="text-sky-300">
                                          ✨ refined
                                        </span>
                                      )}
                                    </div>
                                    {o.vlm_description ? (
                                      <p className="leading-relaxed">{o.vlm_description}</p>
                                    ) : (
                                      <p className="text-muted-foreground">{summarizeDetections(o)}</p>
                                    )}
                                  </div>
                                );
                              }}
                            />
                          );
                        }

                        // Observation
                        const obs = entry.data as Observation;
                        const hasThumb = !!obs.thumbnail_path;
                        const hasFaces = obs.person_detections?.faces && obs.person_detections.faces.length > 0;
                        const namedFaces = obs.person_detections?.faces?.filter((f) => f.person_name) || [];
                        const unknownFaces = obs.person_detections?.faces?.filter((f) => !f.person_name) || [];
                        const objects = obs.object_detections?.objects?.filter((d) => d.label !== "person" && d.label !== "license_plate") || [];
                        const plates = obs.object_detections?.objects?.filter((d) => d.label === "license_plate" && d.plate_text) || [];

                        return (
                          <div key={entry.id} className="rounded-lg border border-border hover:border-accent/50 hover:bg-card/50 overflow-hidden transition-colors">
                            <div className="flex gap-3">
                              {/* Inline thumbnail */}
                              {hasThumb && (
                                <div className="w-24 h-20 flex-shrink-0 bg-black/50 overflow-hidden">
                                  <img src={`/api/observations/${obs.id}/thumbnail${token ? `?token=${token}` : ""}`} alt="" className="w-full h-full object-cover" />
                                </div>
                              )}
                              <div className={`flex-1 min-w-0 py-2 ${hasThumb ? "pr-3" : "px-3"}`}>
                                <div className="flex items-start justify-between gap-2">
                                  <div className="min-w-0 flex-1">
                                    {/* Person names as headline */}
                                    {hasFaces && (
                                      <div className="flex flex-wrap items-center gap-1 mb-1">
                                        {namedFaces.map((f, i) => (
                                          <span key={`n${i}`} className="inline-flex items-center gap-1 text-xs font-medium text-green-400">
                                            {f.person_name}
                                            {f.match_distance != null && <span className="text-[10px] text-muted-foreground">{((1 - f.match_distance) * 100).toFixed(0)}%</span>}
                                            {f.person_id && (
                                              <Link
                                                href={`/follow/person/${f.person_id}`}
                                                onClick={(e) => e.stopPropagation()}
                                                className="ml-0.5 text-[10px] text-accent hover:underline"
                                                title={`Follow ${f.person_name} across cameras`}
                                              >
                                                follow ↗
                                              </Link>
                                            )}
                                          </span>
                                        ))}
                                        {namedFaces.length > 0 && unknownFaces.length > 0 && <span className="text-[10px] text-muted-foreground">+</span>}
                                        {unknownFaces.length > 0 && unknownFaces[0]?.cluster_id ? (
                                          <span className="inline-flex items-center gap-1 text-xs text-yellow-400">
                                            {unknownFaces.length === 1 ? "Unknown person" : `${unknownFaces.length} unknown`}
                                            <Link
                                              href={`/follow/cluster/${unknownFaces[0].cluster_id}`}
                                              onClick={(e) => e.stopPropagation()}
                                              className="ml-0.5 text-[10px] text-accent hover:underline"
                                              title="Follow this recurring stranger"
                                            >
                                              follow ↗
                                            </Link>
                                          </span>
                                        ) : unknownFaces.length > 0 ? (
                                          <span className="text-xs text-yellow-400">{unknownFaces.length === 1 ? "Unknown person" : `${unknownFaces.length} unknown`}</span>
                                        ) : null}
                                      </div>
                                    )}

                                    {/* VLM description (full, 2-line clamp) */}
                                    {obs.vlm_description ? (
                                      <p className="text-xs leading-relaxed line-clamp-2">{obs.vlm_description}</p>
                                    ) : !hasFaces && (
                                      <p className="text-xs font-medium line-clamp-1">{summarizeDetections(obs)}</p>
                                    )}
                                    {obs.refined_by_provider_name && obs.primary_vlm_description && (
                                      <RefinedBadge
                                        primaryText={obs.primary_vlm_description}
                                        refinedText={obs.vlm_description || ""}
                                        refinerProviderName={obs.refined_by_provider_name}
                                      />
                                    )}

                                    {/* Detection tags with confidence */}
                                    <div className="flex flex-wrap items-center gap-1 mt-1">
                                      {objects.slice(0, 6).map((d, i) => (
                                        <span key={i} className="px-1 py-0.5 text-[9px] rounded bg-blue-900/30 text-blue-300 border border-blue-800/40">
                                          {d.label} <span className="text-blue-400/70">{(d.confidence * 100).toFixed(0)}%</span>
                                        </span>
                                      ))}
                                      {objects.length > 6 && <span className="text-[9px] text-muted-foreground">+{objects.length - 6}</span>}
                                      {plates.map((d, i) => (
                                        <span key={`p${i}`} className="px-1 py-0.5 text-[9px] rounded bg-accent/20 text-accent border border-accent/40">{d.plate_text}</span>
                                      ))}
                                      <span className="px-1 py-0.5 text-[9px] rounded bg-muted/50 text-muted-foreground">{cam?.name || "Unknown"}</span>
                                      {obs.vlm_provider && (
                                        <span className="px-1 py-0.5 text-[9px] rounded bg-muted/30 text-muted-foreground font-mono">via {obs.vlm_provider}</span>
                                      )}
                                    </div>
                                  </div>
                                  <span className="text-[10px] text-muted-foreground font-mono flex-shrink-0 pt-0.5">{formatTime(obs.started_at)}</span>
                                </div>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                    )}
                  </div>
                  );
                })}
              </div>
            )}
          </div>
        </main>
      </div>

      <footer className="flex-shrink-0 mt-2 pt-2 border-t border-border/40 flex items-center justify-end gap-3">
        <SystemHealthFooter />
      </footer>

      {modalOpen && <AddCameraModal initialStreamType={modalInitialType} onClose={() => { setModalOpen(false); setModalInitialType(undefined); }} onSuccess={() => { setModalOpen(false); setModalInitialType(undefined); fetchCameras(); }} />}
      {selectedPersonId && (
        <PersonActivityModal
          personId={selectedPersonId}
          personName={personSummaries.find((p) => p.person_id === selectedPersonId)?.display_name || "Person"}
          onClose={() => setSelectedPersonId(null)}
        />
      )}
      {selectedClusterId && (() => {
        const c = clusterSummaries.find((x) => x.cluster_id === selectedClusterId);
        const label = c ? (c.appearance_description ? `${c.auto_label}. ${c.appearance_description}` : c.auto_label) : "Unknown";
        return (
          <PersonActivityModal
            personId={selectedClusterId}
            personName={label}
            mode="cluster"
            onClose={() => setSelectedClusterId(null)}
          />
        );
      })()}
      <RecordingModal
        recording={modalRecording}
        cameraName={modalRecording ? cameras.find((c) => c.id === modalRecording.camera_id)?.name : null}
        onClose={() => setModalRecording(null)}
      />
      <LLMErrorToasts />
      <SecureAccountNudge hasFootage={cameras.length > 0} />
      {cameras.length > 0 && <LocalAIHintCard />}
      {cameras.length > 0 && <AskHintCard />}
      {showWizard && (
        <OnboardingWizard
          onClose={() => setShowWizard(false)}
          onComplete={() => {
            setShowWizard(false);
            fetchCameras();
          }}
        />
      )}
    </div>
  );
}

// Top-right nudge for a provisional owner. Nurby drops a first-run user
// straight into a working feed without forcing signup, so the trade is.
// you're already watching footage, but the account has no password yet.
// This box celebrates the footage and points at securing the account.
// It opens the same claim modal as the navbar's red button.
function SecureAccountNudge({ hasFootage }: { hasFootage: boolean }) {
  const { user } = useAuth();
  const [open, setOpen] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  if (!user?.is_provisional || dismissed) return null;
  return (
    <>
      <div className="fixed top-[4.5rem] right-4 z-40 w-80 rounded-lg border border-red-500/40 bg-card-elevated shadow-xl p-3">
        <div className="flex items-start justify-between gap-2 mb-1.5">
          <div className="text-xs font-semibold flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 pulse-dot" />
            {hasFootage ? "Your footage is live" : "One step left"}
          </div>
          <button
            onClick={() => setDismissed(true)}
            aria-label="Dismiss"
            className="text-muted-foreground hover:text-foreground text-sm leading-none"
          >
            &times;
          </button>
        </div>
        <p className="text-[11px] text-muted-foreground leading-snug mb-2.5">
          {hasFootage
            ? "Nurby is already watching, but you haven't set a password. Anyone who reaches this page is an admin. Lock it down."
            : "You haven't set a password yet, so anyone who reaches this page is an admin. Lock it down."}
        </p>
        <button
          onClick={() => setOpen(true)}
          className="w-full px-3 py-1.5 text-xs font-medium rounded-md bg-red-600 hover:bg-red-500 text-white transition-colors"
        >
          Secure your account
        </button>
      </div>
      {open && <SecureAccountModal onClose={() => setOpen(false)} />}
    </>
  );
}

// Nudge to turn on local AI when no vision provider is configured. The
// product works without a VLM (detection, faces, rules), but scene
// captions and Ask need one. We keep the bundled Ollama opt-in so a plain
// `docker compose up` stays light, and surface the one command here so a
// first-time user gets AI "without doing much". Hidden once a provider is
// active or the user dismisses it.
function LocalAIHintCard() {
  const { authFetch } = useAuth();
  const [show, setShow] = useState(false);
  const [copied, setCopied] = useState(false);
  const cmd = "docker compose --profile local-ai up -d ollama";

  useEffect(() => {
    try {
      if (localStorage.getItem("nurby-localai-hint-dismissed") === "1") return;
    } catch {
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await authFetch("/api/providers");
        if (!res.ok) return;
        const list: { active?: boolean }[] = await res.json();
        // Only nudge when nothing is configured at all.
        if (!cancelled && Array.isArray(list) && !list.some((p) => p.active)) {
          setShow(true);
        }
      } catch {
        /* stay hidden on error */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [authFetch]);

  function dismiss() {
    try {
      localStorage.setItem("nurby-localai-hint-dismissed", "1");
    } catch {
      /* ignore */
    }
    setShow(false);
  }

  function copy() {
    navigator.clipboard?.writeText(cmd).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      },
      () => undefined
    );
  }

  if (!show) return null;
  return (
    <div className="hidden md:block fixed bottom-4 left-4 z-40 w-80 rounded-lg border border-accent/30 bg-card-elevated shadow-xl p-3">
      <div className="flex items-start justify-between gap-2 mb-1.5">
        <div className="text-xs font-semibold flex items-center gap-1.5">
          <span>🧠</span> Add AI descriptions
        </div>
        <button
          onClick={dismiss}
          aria-label="Dismiss"
          className="text-muted-foreground hover:text-foreground text-sm leading-none"
        >
          &times;
        </button>
      </div>
      <p className="text-[11px] text-muted-foreground leading-snug mb-2">
        Nurby already spots motion and faces. Want scene captions and Ask
        Nurby? Run a local model. One command, no API key.
      </p>
      <div className="flex items-center gap-1.5 mb-2">
        <code className="flex-1 text-[10px] font-mono bg-background border border-border rounded px-2 py-1.5 overflow-x-auto whitespace-nowrap">
          {cmd}
        </code>
        <button
          onClick={copy}
          className="text-[10px] px-2 py-1.5 rounded border border-border hover:border-accent/50 hover:text-foreground text-muted-foreground transition-colors flex-shrink-0"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <p className="text-[10px] text-muted-foreground leading-snug">
        Then open{" "}
        <a href="/settings" className="text-accent hover:underline">
          Settings → AI Providers
        </a>{" "}
        and deploy a model in one click. Or skip it. everything else keeps
        working.
      </p>
    </div>
  );
}

// Dismissible nudge toward the agent. The /ask page is the payoff but
// it is just a nav item; a first-time user won't know it exists. Shows
// once (per browser) with example questions that deep-link to a real
// answer via /ask?q=. Hidden after dismissal or first click.
function AskHintCard() {
  const [dismissed, setDismissed] = useState(true);
  useEffect(() => {
    try {
      setDismissed(localStorage.getItem("nurby-ask-hint-dismissed") === "1");
    } catch {
      setDismissed(true);
    }
  }, []);
  function close() {
    try {
      localStorage.setItem("nurby-ask-hint-dismissed", "1");
    } catch {
      /* ignore */
    }
    setDismissed(true);
  }
  if (dismissed) return null;
  const examples = [
    "What happened today?",
    "Was anyone at the door?",
    "Where's the dog right now?",
  ];
  return (
    <div className="hidden md:block fixed bottom-4 right-4 z-40 w-72 rounded-lg border border-accent/30 bg-card-elevated shadow-xl p-3">
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="text-xs font-semibold flex items-center gap-1.5">
          <span>💬</span> Try asking Nurby
        </div>
        <button
          onClick={close}
          aria-label="Dismiss"
          className="text-muted-foreground hover:text-foreground text-sm leading-none"
        >
          &times;
        </button>
      </div>
      <p className="text-[11px] text-muted-foreground leading-tight mb-2">
        Ask in plain English. Nurby investigates your feed and answers with
        evidence.
      </p>
      <div className="space-y-1.5">
        {examples.map((q) => (
          <a
            key={q}
            href={`/ask?q=${encodeURIComponent(q)}`}
            onClick={() => {
              try {
                localStorage.setItem("nurby-ask-hint-dismissed", "1");
              } catch {
                /* ignore */
              }
            }}
            className="block w-full text-left px-2.5 py-1.5 text-[11px] rounded-md border border-border bg-background hover:border-accent/50 hover:bg-accent/5 transition-colors"
          >
            {q}
          </a>
        ))}
      </div>
    </div>
  );
}

export default function HomePage() {
  const { authFetch } = useAuth();
  return (
    <Suspense>
      <DashboardContent />
    </Suspense>
  );
}
