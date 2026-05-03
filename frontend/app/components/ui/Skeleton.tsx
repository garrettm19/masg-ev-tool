import type { CSSProperties } from "react";
import { cn } from "@/lib/cn";

interface SkeletonProps {
  width?: number | string;
  height?: number | string;
  className?: string;
  style?: CSSProperties;
  /** Render as inline-block (default) or block. */
  block?: boolean;
  /** Border radius — defaults to --radius-sm. */
  radius?: "sm" | "md" | "lg" | "full";
}

const RADIUS: Record<NonNullable<SkeletonProps["radius"]>, string> = {
  sm: "var(--radius-sm)",
  md: "var(--radius-md)",
  lg: "var(--radius-lg)",
  full: "999px",
};

export function Skeleton({
  width = "100%",
  height = 12,
  className,
  style,
  block = false,
  radius = "sm",
}: SkeletonProps) {
  return (
    <span
      aria-busy="true"
      aria-live="polite"
      className={cn(block ? "block" : "inline-block", "animate-pulse", className)}
      style={{
        width,
        height,
        background: "var(--bg-surface-2)",
        borderRadius: RADIUS[radius],
        ...style,
      }}
    />
  );
}
