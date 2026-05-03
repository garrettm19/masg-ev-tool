"use client";

import { Button } from "../ui/Button";

interface LiveModeBannerProps {
  show: boolean;
  /** Cooldown in minutes — surfaced in the banner copy so the user
   *  knows the rate limits still apply when live. */
  cooldownMinutes?: number | null;
  maxAlertsPerHour?: number | null;
  onDisable: () => void;
}

/**
 * Persistent danger banner shown whenever live Pushover alerts are
 * active (monitor running AND dry_run=false). Cannot be dismissed —
 * the only way to hide it is to revert to dry-run.
 */
export function LiveModeBanner({
  show,
  cooldownMinutes,
  maxAlertsPerHour,
  onDisable,
}: LiveModeBannerProps) {
  if (!show) return null;

  const limits: string[] = [];
  if (cooldownMinutes != null) limits.push(`cooldown ${cooldownMinutes}m`);
  if (maxAlertsPerHour != null) limits.push(`max ${maxAlertsPerHour}/hr`);
  const limitText = limits.length > 0 ? ` · ${limits.join(", ")}` : "";

  return (
    <div
      role="alert"
      aria-live="polite"
      className="flex items-center justify-between gap-3 px-4 py-2.5 border"
      style={{
        background: "var(--danger-soft)",
        borderColor: "var(--danger-border)",
        borderRadius: "var(--radius-md)",
        boxShadow: "var(--glow-danger)",
      }}
    >
      <div className="flex items-center gap-2 min-w-0">
        <span
          className="w-2 h-2 rounded-full animate-pulse shrink-0"
          style={{
            background: "var(--danger)",
            boxShadow: "0 0 6px var(--danger)",
          }}
          aria-hidden="true"
        />
        <span
          className="font-mono uppercase tracking-wider font-semibold whitespace-nowrap"
          style={{ fontSize: "10px", color: "var(--danger-strong)" }}
        >
          LIVE alerts active
        </span>
        <span
          className="font-mono truncate"
          style={{ fontSize: "10px", color: "var(--danger-strong)" }}
        >
          · Real Pushover notifications fire on every BUY{limitText}
        </span>
      </div>
      <Button
        variant="danger"
        size="sm"
        onClick={onDisable}
        className="shrink-0"
      >
        Switch to Dry-run
      </Button>
    </div>
  );
}
