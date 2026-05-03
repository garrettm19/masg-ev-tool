import type { ReactNode } from "react";
import { cn } from "@/lib/cn";

interface EmptyStateProps {
  /** Optional icon — rendered with reduced opacity above the title. */
  icon?: ReactNode;
  title: string;
  description?: string;
  /** Optional CTA — typically a Button primitive. */
  action?: ReactNode;
  className?: string;
  /** Pad density — "sm" for inline empties, "md" for full-card empties (default). */
  size?: "sm" | "md";
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
  size = "md",
}: EmptyStateProps) {
  const isCompact = size === "sm";
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center text-center",
        isCompact ? "px-4 py-6 gap-2" : "px-6 py-14 gap-3",
        className
      )}
    >
      {icon && (
        <div style={{ opacity: 0.18 }} aria-hidden="true">
          {icon}
        </div>
      )}
      <p
        className="font-mono"
        style={{
          fontSize: isCompact ? "11px" : "12px",
          color: "var(--fg-ghost)",
        }}
      >
        {title}
      </p>
      {description && (
        <p
          className="font-mono max-w-md"
          style={{
            fontSize: isCompact ? "9px" : "10px",
            color: "var(--fg-disabled)",
            lineHeight: 1.5,
          }}
        >
          {description}
        </p>
      )}
      {action && <div className="pt-1">{action}</div>}
    </div>
  );
}
