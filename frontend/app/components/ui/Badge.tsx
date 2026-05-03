import { cn } from "@/lib/cn";

export type BadgeVariant = "accent" | "info" | "warn" | "danger" | "success" | "platform";

interface BadgeProps {
  label: string;
  variant?: BadgeVariant;
  /**
   * Override base color. When provided, the bg/border are derived via
   * color-mix() so any hex/var color produces a coherent treatment.
   * Useful for platform-specific colors (e.g. tokens.platform.kalshi).
   */
  color?: string;
  className?: string;
  title?: string;
}

interface VariantTokens {
  color: string;
  bg: string;
  border: string;
}

const VARIANT_TOKENS: Record<BadgeVariant, VariantTokens> = {
  accent: {
    color: "var(--accent)",
    bg: "var(--accent-soft)",
    border: "var(--accent-border)",
  },
  info: {
    color: "var(--info)",
    bg: "var(--info-soft)",
    border: "var(--info-border)",
  },
  warn: {
    color: "var(--warn-strong)",
    bg: "var(--warn-soft)",
    border: "var(--warn-border)",
  },
  danger: {
    color: "var(--danger-strong)",
    bg: "var(--danger-soft)",
    border: "var(--danger-border)",
  },
  success: {
    color: "var(--success)",
    bg: "var(--success-soft)",
    border: "var(--success-border)",
  },
  platform: {
    color: "var(--fg-secondary)",
    bg: "rgba(148,163,184,0.06)",
    border: "rgba(148,163,184,0.20)",
  },
};

export function Badge({ label, variant = "accent", color, className, title }: BadgeProps) {
  let resolved: VariantTokens;
  if (color) {
    // Caller supplied a base color (hex, rgb, or CSS var). Derive a soft bg
    // and matching border using color-mix so any input produces a coherent
    // chip without the caller having to compute three values.
    resolved = {
      color,
      bg: `color-mix(in oklab, ${color} 8%, transparent)`,
      border: `color-mix(in oklab, ${color} 25%, transparent)`,
    };
  } else {
    resolved = VARIANT_TOKENS[variant];
  }

  return (
    <span
      className={cn(
        "inline-block font-mono uppercase tracking-wider border whitespace-nowrap",
        className
      )}
      style={{
        color: resolved.color,
        background: resolved.bg,
        borderColor: resolved.border,
        fontSize: "8px",
        paddingInline: "6px",
        paddingBlock: "2px",
        borderRadius: "var(--radius-sm)",
      }}
      title={title}
    >
      {label}
    </span>
  );
}
