import { forwardRef, type InputHTMLAttributes, type ReactNode } from "react";
import { cn } from "@/lib/cn";

export type InputSize = "sm" | "md";

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size" | "prefix"> {
  /** Optional content rendered as a leading affordance (e.g. "$"). */
  prefix?: ReactNode;
  /** Optional content rendered as a trailing affordance (e.g. "%", "min"). */
  suffix?: ReactNode;
  inputSize?: InputSize;
  /** Right-align the value (typical for numeric fields). Default true. */
  numeric?: boolean;
}

interface SizeTokens {
  fontSize: string;
  padX: string;
  padY: string;
  affixSize: string;
  affixOffset: number;
}

const SIZE_TOKENS: Record<InputSize, SizeTokens> = {
  sm: { fontSize: "11px", padX: "8px", padY: "4px",  affixSize: "9px",  affixOffset: 8 },
  md: { fontSize: "12px", padX: "10px", padY: "6px", affixSize: "10px", affixOffset: 10 },
};

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    prefix,
    suffix,
    inputSize = "sm",
    numeric = true,
    className,
    style,
    disabled,
    ...rest
  },
  ref
) {
  const s = SIZE_TOKENS[inputSize];
  const padLeft = prefix ? `calc(${s.affixOffset}px + 12px)` : s.padX;
  const padRight = suffix ? `calc(${s.affixOffset}px + 14px)` : s.padX;

  return (
    <div className="relative inline-block w-full">
      {prefix && (
        <span
          className="absolute top-1/2 -translate-y-1/2 font-mono pointer-events-none"
          style={{
            left: s.affixOffset,
            fontSize: s.affixSize,
            color: "var(--fg-ghost)",
          }}
        >
          {prefix}
        </span>
      )}
      <input
        ref={ref}
        disabled={disabled}
        className={cn(
          "w-full border font-mono",
          numeric && "text-right",
          "focus:outline-none focus-visible:[box-shadow:var(--ring-focus)] focus:[border-color:var(--accent-border)]",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          className
        )}
        style={{
          background: "rgba(13,20,22,0.8)",
          borderColor: "var(--border-default)",
          borderRadius: "var(--radius-sm)",
          color: "var(--fg-primary)",
          fontSize: s.fontSize,
          paddingTop: s.padY,
          paddingBottom: s.padY,
          paddingLeft: padLeft,
          paddingRight: padRight,
          ...style,
        }}
        {...rest}
      />
      {suffix && (
        <span
          className="absolute top-1/2 -translate-y-1/2 font-mono pointer-events-none"
          style={{
            right: s.affixOffset,
            fontSize: s.affixSize,
            color: "var(--fg-ghost)",
          }}
        >
          {suffix}
        </span>
      )}
    </div>
  );
});
