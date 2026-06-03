// Canonical camera stream types and discovery shapes. Single source of
// truth shared by the dashboard add-camera modal, the onboarding wizard,
// and the shared CameraForm. Do not re-declare these per surface.

export type StreamType =
  | "rtsp"
  | "http_mjpeg"
  | "http_snapshot"
  | "hls"
  | "usb"
  | "file"
  | "webcam"
  | "audio_rtsp"
  | "browser_mic";

export interface StreamTypeOption {
  value: StreamType;
  label: string;
  hint: string;
  placeholder: string;
}

export const STREAM_TYPES: StreamTypeOption[] = [
  { value: "webcam", label: "This Device", hint: "Use your laptop or phone webcam as a test camera", placeholder: "" },
  { value: "rtsp", label: "RTSP", hint: "IP cameras, NVRs, most security cameras", placeholder: "rtsp://192.168.1.100:554/stream1" },
  { value: "http_mjpeg", label: "HTTP MJPEG", hint: "Motion JPEG over HTTP. Webcams, ESP32-CAM", placeholder: "http://192.168.1.100:8080/video" },
  { value: "http_snapshot", label: "HTTP Snapshot", hint: "Periodic JPEG pull. Low-bandwidth cameras", placeholder: "http://192.168.1.100/snapshot.jpg" },
  { value: "hls", label: "HLS", hint: "HTTP Live Streaming. Cloud cameras, Wyze, Ring", placeholder: "http://192.168.1.100/live/stream.m3u8" },
  { value: "usb", label: "USB / Local", hint: "Locally attached USB or CSI cameras", placeholder: "0" },
  { value: "file", label: "File / Test", hint: "Local or remote video file URL for testing", placeholder: "/path/to/video.mp4" },
  { value: "browser_mic", label: "Phone Mic", hint: "Use a phone or laptop as a wireless mic. No camera needed.", placeholder: "" },
  { value: "audio_rtsp", label: "Network Mic", hint: "Audio-only RTSP, HTTP, or ESP32 mic. No video.", placeholder: "rtsp://mic.local:8554/audio" },
];

export interface DiscoveredDevice {
  index: number;
  path: string;
  name: string;
  resolution: string;
}

export interface DiscoveredOnvifDevice {
  ip: string;
  port: number;
  name: string;
  manufacturer: string;
  model: string;
  firmware: string | null;
  onvif_url: string;
  stream_url: string | null;
  profiles: string[];
  auth_required: boolean;
  resolution: string | null;
  already_added: boolean;
}

export type ModalTab = "manual" | "scan";
