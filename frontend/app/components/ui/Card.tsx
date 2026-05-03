import type { HTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";

export type CardVariant = "card" | "card-subtle" | "tile";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  variant?: CardVariant;
  /** Optional left-side content for the card header. If omitted, no header bar is rendered. */
  header?: ReactNode;
  /** Optional right-side content for the card header (collapse arrow, status dot, etc.). */
  headerRight?: ReactNode;
  /** Disable the default body padding when the child wants to control it (e.g. tables). */
  padding?: boolean;
  children?: ReactNode;
}

const VARIANT_BG: Record<CardVariant, string> = {
  "card": "var(--bg-surface)",
  "card-subtle": "var(--bg-surface)",
  "tile": "var(--bg-overlay)",
};

const VARIANT_BORDER: Record<CardVariant, string> = {
  "card": "var(--border-default)",
  "card-subtle": "var(--border-subtle)",
  "tile": "var(--border-subtle)",
};

const VARIANT_RADIUS: Record<CardVariant, string> = {
  "card": "var(--radius-lg)",
  "card-subtle": "var(--radius-lg)",
  "tile": "var(--radius-md)",
};

const VARIANT_PAD: Record<CardVariant, string> = {
  "card": "12px 16px",
  "card-subtle": "8px 16px",
  "tile": "8px 12px",
};

export function Card({
  variant = "card",
  header,
  headerRight,
  padding = true,
  className,
  style,
  children,
  ...rest
}: CardProps) {
  const hasHeader = header !== undefined || headerRight !== undefined;
  return (
    <div
      className={cn("border overflow-hidden", className)}
      style={{
        background: VARIANT_BG[variant],
        borderColor: VARIANT_BORDER[variant],
        borderRadius: VARIANT_RADIUS[variant],
        ...style,
      }}
      {...rest}
    >
      {hasHeader && (
        <div
          className="flex items-center justify-between px-4 py-2.5 border-b"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <div className="min-w-0">{header}</div>
          {headerRight !== undefined && <div className="shrink-0">{headerRight}</div>}
        </div>
      )}
      <div style={padding ? { padding: VARIANT_PAD[variant] } : undefined}>
        {children}
      </div>
    </div>
  );
}
