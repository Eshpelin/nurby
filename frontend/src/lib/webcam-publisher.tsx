"use client";

// Browser-side webcam publisher. Uses WebRTC WHIP to push getUserMedia
// stream into MediaMTX, so the rest of the pipeline can consume it as
// a regular RTSP source at rtsp://localhost:8554/<streamPath>.

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

const WEBRTC_URL = process.env.NEXT_PUBLIC_WEBRTC_URL || "http://localhost:8889";

export interface WebcamPublisher {
  streamPath: string;
  cameraId: string | null;
  cameraName: string;
  status: "connecting" | "live" | "error";
  error?: string;
}

interface WebcamContextValue {
  publishers: WebcamPublisher[];
  startPublish: (opts: {
    streamPath: string;
    cameraName: string;
    stream: MediaStream;
  }) => Promise<void>;
  attachCameraId: (streamPath: string, cameraId: string) => void;
  stopPublish: (streamPath: string) => void;
}

const WebcamContext = createContext<WebcamContextValue | null>(null);

interface ActiveSession {
  pc: RTCPeerConnection;
  stream: MediaStream;
  resource: string | null; // WHIP resource URL for DELETE on stop
}

export function WebcamPublisherProvider({ children }: { children: React.ReactNode }) {
  const sessionsRef = useRef<Map<string, ActiveSession>>(new Map());
  const [publishers, setPublishers] = useState<WebcamPublisher[]>([]);

  const upsert = useCallback((p: WebcamPublisher) => {
    setPublishers((prev) => {
      const next = prev.filter((x) => x.streamPath !== p.streamPath);
      next.push(p);
      return next;
    });
  }, []);

  const remove = useCallback((streamPath: string) => {
    setPublishers((prev) => prev.filter((x) => x.streamPath !== streamPath));
  }, []);

  const startPublish = useCallback(async (opts: { streamPath: string; cameraName: string; stream: MediaStream }) => {
    const { streamPath, cameraName, stream } = opts;
    upsert({ streamPath, cameraId: null, cameraName, status: "connecting" });

    const pc = new RTCPeerConnection({
      iceServers: [{ urls: "stun:stun.l.google.com:19302" }],
    });

    stream.getTracks().forEach((t) => pc.addTrack(t, stream));

    // WHIP expects a single offer/answer exchange with full ICE candidates
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    // Wait for ICE gathering to complete so SDP has all candidates
    await new Promise<void>((resolve) => {
      if (pc.iceGatheringState === "complete") return resolve();
      const check = () => {
        if (pc.iceGatheringState === "complete") {
          pc.removeEventListener("icegatheringstatechange", check);
          resolve();
        }
      };
      pc.addEventListener("icegatheringstatechange", check);
      // Safety timeout
      setTimeout(resolve, 3000);
    });

    try {
      const res = await fetch(`${WEBRTC_URL}/${streamPath}/whip`, {
        method: "POST",
        headers: { "Content-Type": "application/sdp" },
        body: pc.localDescription?.sdp ?? "",
      });
      if (!res.ok) {
        const body = await res.text().catch(() => "");
        throw new Error(`WHIP publish failed (${res.status}): ${body || "no body"}`);
      }
      const answerSdp = await res.text();
      const resource = res.headers.get("Location") || res.headers.get("location") || null;
      await pc.setRemoteDescription({ type: "answer", sdp: answerSdp });

      sessionsRef.current.set(streamPath, { pc, stream, resource });
      upsert({ streamPath, cameraId: null, cameraName, status: "live" });

      pc.addEventListener("connectionstatechange", () => {
        if (pc.connectionState === "failed" || pc.connectionState === "closed") {
          upsert({ streamPath, cameraId: null, cameraName, status: "error", error: pc.connectionState });
        }
      });
    } catch (err) {
      pc.close();
      stream.getTracks().forEach((t) => t.stop());
      const msg = err instanceof Error ? err.message : String(err);
      upsert({ streamPath, cameraId: null, cameraName, status: "error", error: msg });
      throw err;
    }
  }, [upsert]);

  const attachCameraId = useCallback((streamPath: string, cameraId: string) => {
    setPublishers((prev) => prev.map((p) => p.streamPath === streamPath ? { ...p, cameraId } : p));
  }, []);

  const stopPublish = useCallback((streamPath: string) => {
    const session = sessionsRef.current.get(streamPath);
    if (session) {
      session.stream.getTracks().forEach((t) => t.stop());
      session.pc.close();
      if (session.resource) {
        // WHIP spec. DELETE resource to tear down cleanly
        const url = session.resource.startsWith("http") ? session.resource : `${WEBRTC_URL}${session.resource}`;
        fetch(url, { method: "DELETE" }).catch(() => { /* best-effort */ });
      }
      sessionsRef.current.delete(streamPath);
    }
    remove(streamPath);
  }, [remove]);

  // Stop all on unmount
  useEffect(() => {
    const sessions = sessionsRef.current;
    return () => {
      sessions.forEach(({ pc, stream }) => {
        stream.getTracks().forEach((t) => t.stop());
        pc.close();
      });
      sessions.clear();
    };
  }, []);

  return (
    <WebcamContext.Provider value={{ publishers, startPublish, attachCameraId, stopPublish }}>
      {children}
    </WebcamContext.Provider>
  );
}

export function useWebcamPublisher() {
  const ctx = useContext(WebcamContext);
  if (!ctx) throw new Error("useWebcamPublisher must be used within WebcamPublisherProvider");
  return ctx;
}

// Enumerate video devices. Triggers a brief getUserMedia prompt if labels
// aren't yet available (browsers hide labels until permission granted).
export async function listVideoDevices(): Promise<MediaDeviceInfo[]> {
  const devices = await navigator.mediaDevices.enumerateDevices();
  const videos = devices.filter((d) => d.kind === "videoinput");
  if (videos.length === 0) return [];
  // If labels are empty, request permission once to unmask them
  if (videos.every((d) => !d.label)) {
    try {
      const tmp = await navigator.mediaDevices.getUserMedia({ video: true });
      tmp.getTracks().forEach((t) => t.stop());
      const again = await navigator.mediaDevices.enumerateDevices();
      return again.filter((d) => d.kind === "videoinput");
    } catch {
      return videos;
    }
  }
  return videos;
}
