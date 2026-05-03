import { forwardRef, type InputHTMLAttributes, useId } from "react";
import { cn } from "@/lib/cn";

export type ToggleSize = "sm" | "md";

interface ToggleProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "size" | "onChange" | "checked"> {
  checked: boolean;
  onCheckedChange: (next: boolean) => void;
  label?: string;
  /**
   * When defined, applies danger styling whenever `checked === dangerWhen`.
   * Use case: dry-run toggle for live alerts — pass `dangerWhen={false}` so
   * flipping dry-run OFF (i.e. live alerts ON) makes the switch read red.
   */
  dangerWhen?: boolean;
  size?: ToggleSize;
}

interface SizeTokens {
  trackW: number;
  trackH: number;
  thumb: number;
  pad: number;
}

const SIZE_TOKENS: Record<ToggleSize, SizeTokens> = {
  sm: { trackW: 28, trackH: 16, thumb: 12, pad: 2 },
  md: { trackW: 36, trackH: 20, thumb: 16, pad: 2 },
};

export const Toggle = forwardRef<HTMLInputElement, ToggleProps>(function Toggle(
  { checked, onCheckedChange, label, dangerWhen, size = "sm", disabled, id: idProp, className, ...rest },
  ref
) {
  const reactId = useId();
  const id = idProp ?? reactId;
  const s = SIZE_TOKENS[size];
  const showDanger = dangerWhen !== undefined && checked === dangerWhen;
  const trackOnColor = showDanger ? "var(--danger)" : "var(--accent)";
  const trackOffColor = showDanger ? "var(--danger)" : "var(--fg-ghost)";
  const trackColor = checked ? trackOnColor : trackOffColor;
  const labelColor = showDanger
    ? "var(--danger-strong)"
    : checked
      ? "var(--fg-primary)"
      : "var(--fg-faint)";

  const thumbX = checked ? s.trackW - s.thumb - s.pad : s.pad;

  return (
    <label
      htmlFor={id}
      className={cn(
        "inline-flex items-center gap-2 cursor-pointer select-none",
        disabled && "cursor-not-allowed opacity-50",
        className
      )}
    >
      <input
        ref={ref}
        id={id}
        type="checkbox"
        role="switch"
        aria-checked={checked}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onCheckedChange(e.target.checked)}
        className="sr-only peer"
        {...rest}
      />
      <span
        aria-hidden="true"
        className={cn(
          "relative inline-block transition-colors duration-150",
          "peer-focus-visible:[box-shadow:var(--ring-focus)]"
        )}
        style={{
          width: s.trackW,
          height: s.trackH,
          borderRadius: 999,
          background: trackColor,
        }}
      >
        <span
          aria-hidden="true"
          className="absolute top-1/2 -translate-y-1/2 transition-[left] duration-150 ease-out"
          style={{
            left: thumbX,
            width: s.thumb,
            height: s.thumb,
            borderRadius: 999,
            background: "#ffffff",
            boxShadow: "0 1px 2px rgba(0,0,0,0.4)",
          }}
        />
      </span>
      {label && (
        <span
          className="font-mono"
          style={{ fontSize: "10px", color: labelColor }}
        >
          {label}
        </span>
      )}
    </label>
  );
});
