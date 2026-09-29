"use client";

import { useEffect, useRef, useState } from "react";
import { useAuth } from "@/lib/auth";
import { translate } from "@/lib/i18n";

/** Browser WHEP client using the API's camera-scoped signaling proxy. */
export function WhepPlayer({ cameraId, onFailed }: { cameraId: string; onFailed?: () => void }) {
  const { authFetch, user } = useAuth();
  const t = (key: string) => translate(user?.locale, key);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const [state, setState] = useState<"connecting" | "failed">("connecting");

  useEffect(() => {
    let disposed = false;
    let peer: RTCPeerConnection | null = null;
    let sessionUrl: string | null = null;

    const fail = () => {
      if (disposed) return;
      setState("failed");
      onFailed?.();
    };

    const connect = async () => {
      try {
        peer = new RTCPeerConnection({ iceServers: [] });
        peer.ontrack = (event) => {
          const stream = event.streams[0];
          if (stream && videoRef.current) {
            videoRef.current.srcObject = stream;
            void videoRef.current.play().catch(() => undefined);
          }
        };
        peer.onconnectionstatechange = () => {
          if (peer?.connectionState === "failed" || peer?.connectionState === "closed") fail();
        };
        peer.addTransceiver("video", { direction: "recvonly" });
        peer.addTransceiver("audio", { direction: "recvonly" });
        const offer = await peer.createOffer();
        await peer.setLocalDescription(offer);
        if (peer.iceGatheringState !== "complete") {
          await new Promise<void>((resolve) => {
            const timer = window.setTimeout(resolve, 3000);
            peer!.onicegatheringstatechange = () => {
              if (peer?.iceGatheringState === "complete") {
                window.clearTimeout(timer);
                resolve();
              }
            };
          });
        }
        const local = peer.localDescription;
        if (!local?.sdp) throw new Error("Missing SDP offer");
        const response = await authFetch(`/api/cameras/${cameraId}/whep`, {
          method: "POST",
          headers: { "Content-Type": "application/sdp", Accept: "application/sdp" },
          body: local.sdp,
        });
        if (!response.ok) throw new Error(`WHEP ${response.status}`);
        sessionUrl = response.headers.get("location");
        const answer = await response.text();
        await peer.setRemoteDescription({ type: "answer", sdp: answer });
      } catch {
        fail();
      }
    };

    void connect();
    return () => {
      disposed = true;
      if (videoRef.current) videoRef.current.srcObject = null;
      peer?.close();
      if (sessionUrl) {
        void authFetch(sessionUrl, { method: "DELETE" }).catch(() => undefined);
      }
    };
  }, [authFetch, cameraId, onFailed]);

  return (
    <div className="absolute inset-0 bg-black">
      <video ref={videoRef} autoPlay muted playsInline className="absolute inset-0 h-full w-full object-cover" />
      {state === "connecting" && <div className="absolute inset-0 flex items-center justify-center text-[10px] text-muted-foreground">{t("camera_player.connecting")}</div>}
      {state === "failed" && <div className="absolute inset-0 flex items-center justify-center text-[10px] text-muted-foreground">{t("camera_player.unavailable")}</div>}
    </div>
  );
}
