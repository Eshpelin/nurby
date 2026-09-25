"use client";

/**
 * The live-feed layer of a camera tile, shared by the dashboard wall and
 * the camera workspace (#319): picks the right renderer for the stream
 * type — WebRTC (MediaMTX) for rtsp/hls and muxed webcams, a direct
 * <video> for remote and local files, the local MediaStream for a webcam
 * this tab captures, and an honest offline box otherwise.
 *
 * Extracted from CameraSidebarCard so the camera workspace can show the
 * same feed with the same fallbacks instead of nothing at all. Callers
 * own the positioning container (the render is absolutely positioned
 * inside it).
 *
 * MediaMTX serves the muxed copy under a canonical slug (mux_slug on the
 * backend), NOT the camera's own URL path. rtsp/hls pull-mux under
 * cam-<id>; webcam/usb push under webcam-<id>. Using the URL's last path
 * segment ("stream1") requests a path MediaMTX does not have, so the
 * player would show "stream not found".
 */

import { useEffect, useRef } from "react";
import Link from "next/link";
import { useWebcamPublisher } from "@/lib/webcam-publisher";
import { RetryCountdown } from "@/components/RetryCountdown";
import { extractStreamName, WEBRTC_URL } from "@/app/dashboard-helpers";
import { useAuth } from "@/lib/auth";

// Structural: the dashboard wall passes its rich Camera type, the camera
// workspace its settings-page type — both carry these fields.
export interface CameraPlayerCamera {
  id: string;
  stream_type: string;
  stream_url: string;
  status: string;
  audio_only?: boolean;
  audio_capture_enabled?: boolean;
  status_reason?: string | null;
  next_retry_at?: string | number | null;
}

export function CameraPlayer({
  camera,
  objectFit = "cover",
}: {
  camera: CameraPlayerCamera;
  // "cover" fills small tiles (may crop); "contain" letterboxes a large
  // viewer (the workspace) so the whole frame stays visible.
  objectFit?: "cover" | "contain";
}) {
  // A remote-file camera (the demo, or any http(s) clip) is not muxed into
  // MediaMTX, so the WebRTC path would be empty and the player black. The
  // browser can play the URL directly, so render a looping <video>. This
  // also means the demo shows footage within seconds, independent of the
  // ingestion poll + connect cycle.
  const isRemoteFile =
    camera.stream_type === "file" && /^https?:\/\//.test(camera.stream_url);
  const { token } = useAuth();
  const isLocalFile = camera.stream_type === "file" && !isRemoteFile;
  const localFilePreview = isLocalFile && token
    ? `/api/cameras/${camera.id}/preview?token=${encodeURIComponent(token)}`
    : null;
  const isPlayableFile = isRemoteFile || Boolean(localFilePreview);

  // Webcam publisher state. If this tab owns the capture we render the
  // local MediaStream directly in a <video> element.
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

  const streamName =
    camera.stream_type === "rtsp" || camera.stream_type === "hls"
      ? `cam-${camera.id}`
      : camera.stream_type === "webcam" || camera.stream_type === "usb"
        ? `webcam-${camera.id}`
        : extractStreamName(camera.stream_url);
  const iframeSrc = `${WEBRTC_URL}/${streamName}/`;
  const fitClass = objectFit === "contain" ? "object-contain" : "object-cover";

  if (camera.audio_only) {
    return (
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
            className="text-[11px] px-2.5 py-1 rounded-md border border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10"
          >
            Open mic page →
          </Link>
        )}
      </div>
    );
  }

  if (isPlayableFile) {
    return (
      <video
        src={isRemoteFile ? camera.stream_url : localFilePreview ?? undefined}
        autoPlay
        muted
        loop
        playsInline
        className={`absolute inset-0 w-full h-full ${fitClass}`}
      />
    );
  }

  if (isWebcam && localStream) {
    return (
      <video
        ref={webcamVideoRef}
        autoPlay
        muted
        playsInline
        className={`absolute inset-0 w-full h-full ${fitClass}`}
      />
    );
  }

  if (camera.status !== "offline") {
    return (
      <iframe
        src={iframeSrc}
        className="absolute inset-0 w-full h-full border-0 pointer-events-none"
        allow="autoplay; encrypted-media"
        sandbox="allow-scripts allow-same-origin"
      />
    );
  }

  // Offline. For file cameras this reads oddly on its own — the browser is
  // usually still playing the clip — so say what is actually happening
  // (#319): the picture exists, the decoder does not, so no detections.
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-2">
      {camera.stream_type === "file" ? (
        <>
          <span
            className="text-[10px] text-muted-foreground font-mono"
            title="A file camera plays in your browser, but Nurby's decoder is not running, so nothing is being detected or recorded right now."
          >
            FILE · PLAYER ONLY
          </span>
          <span className="text-[9px] text-muted-foreground/70 text-center px-2">
            No decoder running — detections and recording are paused.
          </span>
        </>
      ) : (
        <span className="text-[10px] text-muted-foreground font-mono">OFFLINE</span>
      )}
      {!isWebcam && (camera.status_reason || camera.next_retry_at) && (
        <RetryCountdown
          className="text-[10px] text-center px-2"
          nextRetryAt={camera.next_retry_at as number | null | undefined}
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
  );
}
