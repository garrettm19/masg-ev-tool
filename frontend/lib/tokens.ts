/**
 * Type-safe token constants — string values are CSS var() references that
 * resolve against globals.css :root tokens. Use in TS where utility classes
 * aren't expressive enough (Recharts colors, dynamic style merges, etc.).
 *
 * Example:
 *   <div style={{ color: tokens.accent.base, background: tokens.bg.surface }} />
 */

export const tokens = {
  bg: {
    canvas: "var(--bg-canvas)",
    surface: "var(--bg-surface)",
    surface2: "var(--bg-surface-2)",
    overlay: "var(--bg-overlay)",
  },
  border: {
    subtle: "var(--border-subtle)",
    default: "var(--border-default)",
    strong: "var(--border-strong)",
  },
  fg: {
    primary: "var(--fg-primary)",
    secondary: "var(--fg-secondary)",
    muted: "var(--fg-muted)",
    faint: "var(--fg-faint)",
    ghost: "var(--fg-ghost)",
    disabled: "var(--fg-disabled)",
  },
  accent: {
    base: "var(--accent)",
    soft: "var(--accent-soft)",
    border: "var(--accent-border)",
  },
  info: {
    base: "var(--info)",
    soft: "var(--info-soft)",
    border: "var(--info-border)",
  },
  warn: {
    base: "var(--warn)",
    strong: "var(--warn-strong)",
    soft: "var(--warn-soft)",
    border: "var(--warn-border)",
  },
  danger: {
    base: "var(--danger)",
    strong: "var(--danger-strong)",
    soft: "var(--danger-soft)",
    border: "var(--danger-border)",
  },
  success: {
    base: "var(--success)",
    soft: "var(--success-soft)",
    border: "var(--success-border)",
  },
  platform: {
    polymarket: "var(--platform-polymarket)",
    kalshi: "var(--platform-kalshi)",
    fanduel: "var(--platform-fanduel)",
  },
  edge: {
    elite: "var(--edge-elite)",
    strong: "var(--edge-strong)",
    soft: "var(--edge-soft)",
    mute: "var(--edge-mute)",
  },
  radius: {
    sm: "var(--radius-sm)",
    md: "var(--radius-md)",
    lg: "var(--radius-lg)",
    xl: "var(--radius-xl)",
  },
  ring: {
    focus: "var(--ring-focus)",
  },
  glow: {
    active: "var(--glow-active)",
    danger: "var(--glow-danger)",
  },
} as const;

export type Tokens = typeof tokens;
