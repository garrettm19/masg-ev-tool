"use client";

import { useEffect, useId, useRef, type ReactNode } from "react";
import { Button, type ButtonVariant } from "./Button";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  /** Variant for the confirm button — use "danger" for destructive/risky
   *  confirms (live alert enable), "primary" for routine. */
  confirmVariant?: ButtonVariant;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Modal confirm dialog. Backdrop click and Escape both cancel. Initial
 * focus lands on the cancel button (the safer default — the user can hit
 * Enter to back out without reading the body). Renders nothing when
 * `open` is false.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  confirmVariant = "primary",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const cancelBtnRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descId = useId();

  useEffect(() => {
    if (!open) return;
    cancelBtnRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onCancel();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      aria-describedby={descId}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: "rgba(7,9,10,0.78)" }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <div
        className="max-w-md w-full"
        style={{
          background: "var(--bg-surface)",
          borderRadius: "var(--radius-lg)",
          border: "1px solid var(--border-default)",
          boxShadow: "0 20px 60px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.02)",
        }}
      >
        <div
          className="px-5 py-4 border-b"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <h2
            id={titleId}
            className="font-mono uppercase tracking-wider font-semibold"
            style={{ fontSize: "12px", color: "var(--fg-primary)" }}
          >
            {title}
          </h2>
        </div>
        <div
          id={descId}
          className="px-5 py-4 max-h-[60vh] overflow-y-auto font-mono leading-relaxed"
          style={{ fontSize: "11px", color: "var(--fg-secondary)" }}
        >
          {description}
        </div>
        <div
          className="px-5 py-3 border-t flex items-center justify-end gap-2"
          style={{ borderColor: "var(--border-subtle)" }}
        >
          <Button
            ref={cancelBtnRef}
            variant="ghost"
            size="md"
            onClick={onCancel}
          >
            {cancelLabel}
          </Button>
          <Button variant={confirmVariant} size="md" onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
