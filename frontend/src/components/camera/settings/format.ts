  function formatInterval(seconds: number): string {
    if (seconds === 0) return "Every keyframe";
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60 ? `${seconds % 60}s` : ""}`.trim();
    return `${Math.floor(seconds / 3600)}h`;
  }

export { formatInterval };
