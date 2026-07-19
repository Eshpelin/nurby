"""Redis stream / key names shared across services.

Kept here so a consumer (e.g. the perception camera-status watcher) can name
the stream without importing a producer module like
``services.ingestion.stream`` and dragging in its heavy deps (OpenCV, the
video writer). The perception image does not even ship ``services/ingestion``,
so that import crash-loops the process.
"""

# Camera availability edges (offline / back online) for the rule engine.
# A stream rather than pubsub so a transition that happens while the
# perception process is restarting is delivered when it comes back, not
# lost. Tamper alerting cannot ride a fire-and-forget channel.
CAMERA_STATUS_STREAM_KEY = "nurby:camera_status"
CAMERA_STATUS_STREAM_MAXLEN = 500
