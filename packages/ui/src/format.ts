export function formatTime(epochSeconds?: number | null): string {
  if (!epochSeconds) return "—";
  return new Date(epochSeconds * 1000).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function timeAgo(epochSeconds?: number | null): string {
  if (!epochSeconds) return "never";
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - epochSeconds));
  if (seconds < 60) return `${seconds}s ago`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export function shortHash(value?: string | null, length = 8): string {
  return value ? value.slice(0, length) : "—";
}

export function money(minor?: number | null): string {
  return minor == null ? "—" : `${(minor / 100).toFixed(2)} BDT`;
}

export function pct(value?: number | null): string {
  return value == null ? "no applicable controls assessed" : `${value}%`;
}
