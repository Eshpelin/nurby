const STREAM_TYPES: Record<string, string> = {
  rtsp: "RTSP",
  http_mjpeg: "HTTP MJPEG",
  http_snapshot: "HTTP Snapshot",
  hls: "HLS",
  usb: "USB / Local",
  file: "File / Test",
};

const DEFAULT_VLM_PROMPT =
  "You are a security camera AI assistant. Describe what you see in this camera frame in 1-2 concise sentences. Focus on people, vehicles, animals, and any unusual activity. Be specific about locations, actions, and counts. If nothing notable is happening, say so briefly.";

export { STREAM_TYPES, DEFAULT_VLM_PROMPT };
