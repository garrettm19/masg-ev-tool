import { forwardRef, type ButtonHTMLAttributes, type CSSProperties } from "react";
import { cn } from "@/lib/cn";

export type ButtonVariant = "primary" | "danger" | "secondary" | "ghost";
export type ButtonSize = "sm" | "md";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
}

interface VariantTokens {
  color: string;
  bg: string;
  bgHover: string;
  border: string;
  borderHover: string;
}

const VARIANT_TOKENS: Record<ButtonVariant, VariantTokens> = {
  primary: {
    color: "var(--accent)",
    bg: "var(--accent-soft)",
    bgHover: "rgba(45,212,191,0.14)",
    border: "var(--accent-border)",
    borderHover: "rgba(45,212,191,0.45)",
  },
  danger: {
    color: "var(--danger-strong)",
    bg: "var(--danger-soft)",
    bgHover: "rgba(239,68,68,0.14)",
    border: "var(--danger-border)",
    borderHover: "rgba(239,68,68,0.50)",
  },
  secondary: {
    color: "var(--warn-strong)",
    bg: "var(--warn-soft)",
    bgHover: "rgba(245,158,11,0.14)",
    border: "var(--warn-border)",
    borderHover: "rgba(245,158,11,0.45)",
  },
  ghost: {
    color: "var(--fg-secondary)",
    bg: "transparent",
    bgHover: "rgba(75,85,99,0.10)",
    border: "rgba(75,85,99,0.20)",
    borderHover: "rgba(75,85,99,0.40)",
  },
};

interface SizeTokens {
  px: string;
  py: string;
  minH: string;
  fontSize: string;
}

const SIZE_TOKENS: Record<ButtonSize, SizeTokens> = {
  sm: { px: "10px", py: "4px", minH: "28px", fontSize: "10px" },
  md: { px: "16px", py: "8px", minH: "36px", fontSize: "11px" },
};

interface CSSVarStyle extends CSSProperties {
  "--btn-bg-hover"?: string;
  "--btn-border-hover"?: string;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "sm",
    loading = false,
    disabled,
    className,
    style,
    children,
    type = "button",
    ...rest
  },
  ref
) {
  const v = VARIANT_TOKENS[variant];
  const s = SIZE_TOKENS[size];
  const isDisabled = disabled || loading;

  const composedStyle: CSSVarStyle = {
    color: v.color,
    background: v.bg,
    borderColor: v.border,
    borderRadius: "var(--radius-md)",
    paddingInline: s.px,
    paddingBlock: s.py,
    minHeight: s.minH,
    fontSize: s.fontSize,
    "--btn-bg-hover": v.bgHover,
    "--btn-border-hover": v.borderHover,
    ...style,
  };

  return (
    <button
      ref={ref}
      type={type}
      disabled={isDisabled}
      data-variant={variant}
      data-size={size}
      className={cn(
        "ui-btn",
        "inline-flex items-center justify-center gap-1.5 font-mono tracking-wider uppercase border transition-colors duration-150",
        "focus:outline-none focus-visible:[box-shadow:var(--ring-focus)]",
        "disabled:opacity-40 disabled:cursor-not-allowed",
        "enabled:hover:[background:var(--btn-bg-hover)] enabled:hover:[border-color:var(--btn-border-hover)]",
        className
      )}
      style={composedStyle}
      {...rest}
    >
      {loading ? "..." : children}
    </button>
  );
});
