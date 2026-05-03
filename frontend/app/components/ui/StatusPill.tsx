import { cn } from "@/lib/cn";

export type StatusPillTone =
  | "neutral"
  | "accent"
  | "info"
  | "warn"
  | "danger"
  | "success"
  | "muted";

export type StatusPillVariant = "solid" | "outline" | "dashed" | "live" | "ghost";

export type StatusPillSize = "xs" | "sm" | "md";

interface StatusPillProps {
  /** Optional all-caps label rendered before the value (e.g. "SCAN"). */
  label?: string;
  value: string;
  tone?: StatusPillTone;
  variant?: StatusPillVariant;
  size?: StatusPillSize;
  pulse?: boolean;
  /** Optional secondary detail rendered after the value (e.g. "12s elapsed"). */
  detail?: string | null;
  title?: string;
  /** Hide the leading status dot (useful for outline/ghost variants used inline). */
  showDot?: boolean;
}

interface ToneTokens {
  dot: string;
  text: string;
  bg: string;
  border: string;
}

const TONE_COLORS: Record<StatusPillTone, ToneTokens> = {
  neutral: {
    dot: "#64748b",
    text: "#94a3b8",
    bg: "rgba(100,116,139,0.06)",
    border: "rgba(100,116,139,0.20)",
  },
  accent: {
    dot: "var(--accent)",
    text: "var(--accent)",
    bg: "var(--accent-soft)",
    border: "var(--accent-border)",
  },
  info: {
    dot: "var(--info)",
    text: "var(--info)",
    bg: "var(--info-soft)",
    border: "var(--info-border)",
  },
  warn: {
    dot: "var(--warn)",
    text: "var(--warn-strong)",
    bg: "var(--warn-soft)",
    border: "var(--warn-border)",
  },
  danger: {
    dot: "var(--danger)",
    text: "var(--danger-strong)",
    bg: "var(--danger-soft)",
    border: "var(--danger-border)",
  },
  success: {
    dot: "var(--success)",
    text: "var(--success)",
    bg: "var(--success-soft)",
    border: "var(--success-border)",
  },
  muted: {
    dot: "var(--fg-ghost)",
    text: "var(--fg-faint)",
    bg: "rgba(55,65,81,0.05)",
    border: "rgba(55,65,81,0.20)",
  },
};

interface SizeTokens {
  px: string;
  py: string;
  labelSize: string;
  valueSize: string;
  detailSize: string;
  gap: string;
  dot: number;
}

const SIZE_TOKENS: Record<StatusPillSize, SizeTokens> = {
  xs: { px: "8px",  py: "4px", labelSize: "8px",  valueSize: "10px", detailSize: "9px",  gap: "6px",  dot: 5 },
  sm: { px: "12px", py: "6px", labelSize: "9px",  valueSize: "11px", detailSize: "9px",  gap: "8px",  dot: 6 },
  md: { px: "14px", py: "8px", labelSize: "10px", valueSize: "13px", detailSize: "10px", gap: "10px", dot: 7 },
};

export function StatusPill({
  label,
  value,
  tone = "neutral",
  variant = "solid",
  size = "sm",
  pulse = false,
  detail,
  title,
  showDot = true,
}: StatusPillProps) {
  const t = TONE_COLORS[tone];
  const s = SIZE_TOKENS[size];

  const isOutline = variant === "outline";
  const isDashed = variant === "dashed";
  const isLive = variant === "live";
  const isGhost = variant === "ghost";

  const background = isGhost ? "transparent" : isOutline ? "transparent" : t.bg;
  const borderStyle = isDashed ? "dashed" : "solid";
  const border = isGhost ? "none" : `1px ${borderStyle} ${t.border}`;
  const boxShadow = isLive ? `0 0 8px ${t.dot}, inset 0 0 0 1px ${t.border}` : undefined;

  return (
    <div
      className={cn("inline-flex items-center font-mono")}
      style={{
        gap: s.gap,
        paddingInline: s.px,
        paddingBlock: s.py,
        borderRadius: "var(--radius-md)",
        border,
        background,
        boxShadow,
      }}
      title={title}
    >
      {showDot && (
        <span
          className={cn("rounded-full inline-block", pulse && "animate-pulse")}
          style={{
            width: s.dot,
            height: s.dot,
            background: t.dot,
            boxShadow: pulse || isLive ? `0 0 6px ${t.dot}` : "none",
          }}
        />
      )}
      {label && (
        <span
          className="tracking-[0.18em] uppercase"
          style={{ fontSize: s.labelSize, color: "var(--fg-faint)" }}
        >
          {label}
        </span>
      )}
      <span
        className="font-semibold"
        style={{ fontSize: s.valueSize, color: t.text }}
      >
        {value}
      </span>
      {detail != null && detail !== "" && (
        <span
          className="font-mono"
          style={{ fontSize: s.detailSize, color: "var(--fg-faint)" }}
        >
          · {detail}
        </span>
      )}
    </div>
  );
}
