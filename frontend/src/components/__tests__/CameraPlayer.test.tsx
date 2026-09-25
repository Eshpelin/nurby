import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CameraPlayer } from "@/components/CameraPlayer";
import type { CameraPlayerCamera } from "@/components/CameraPlayer";

const mocks = vi.hoisted(() => ({ token: "test-token" as string | null }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ token: mocks.token }) }));
vi.mock("@/lib/webcam-publisher", () => ({
  useWebcamPublisher: () => ({ publishers: [], resumeIntent: () => {} }),
}));

afterEach(cleanup);

function camera(overrides: Partial<CameraPlayerCamera> = {}): CameraPlayerCamera {
  return {
    id: "cam-1",
    stream_type: "rtsp",
    stream_url: "rtsp://192.168.1.100:554/stream1",
    status: "live",
    ...overrides,
  };
}

describe("CameraPlayer", () => {
  it("renders the WebRTC iframe for a live rtsp camera", () => {
    render(<CameraPlayer camera={camera()} />);
    const frame = screen.getByTitle || screen.queryByTitle;
    const iframe = document.querySelector("iframe");
    expect(iframe).not.toBeNull();
    expect(iframe?.src).toContain("cam-cam-1");
  });

  it("plays a remote file camera directly in a video element", () => {
    render(
      <CameraPlayer
        camera={camera({ stream_type: "file", stream_url: "https://example.com/loop.mp4" })}
      />,
    );
    const video = document.querySelector("video");
    expect(video).not.toBeNull();
    expect(video?.getAttribute("src")).toBe("https://example.com/loop.mp4");
  });

  it("plays a local file camera through the token-authed preview", () => {
    render(<CameraPlayer camera={camera({ stream_type: "file", stream_url: "/data/recordings/x.mp4" })} />);
    const video = document.querySelector("video");
    expect(video?.getAttribute("src")).toContain("/api/cameras/cam-1/preview?token=");
  });

  it("keeps playing a file camera even when the decoder is offline", () => {
    // The browser plays the clip directly, independent of the ingestion
    // worker; the "file · player only" qualifier lives in the workspace
    // header, while the player itself keeps showing the picture.
    render(
      <CameraPlayer
        camera={camera({ stream_type: "file", stream_url: "https://example.com/loop.mp4", status: "offline" })}
      />,
    );
    expect(document.querySelector("video")?.getAttribute("src")).toBe("https://example.com/loop.mp4");
    expect(screen.queryByText("OFFLINE")).toBeNull();
  });

  it("shows a plain OFFLINE box for an offline rtsp camera", () => {
    render(<CameraPlayer camera={camera({ status: "offline" })} />);
    expect(screen.getByText("OFFLINE")).toBeInTheDocument();
    expect(document.querySelector("video")).toBeNull();
  });

  it("renders the audio-only placeholder for a mic", () => {
    render(<CameraPlayer camera={camera({ audio_only: true, stream_type: "network_mic" })} />);
    expect(screen.getByText("Audio-only mic")).toBeInTheDocument();
  });
});
