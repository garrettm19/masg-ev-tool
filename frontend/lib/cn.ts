/**
 * Tiny classNames helper. No dependency on clsx/tailwind-merge.
 * Falsy values (false, null, undefined, "") are dropped; arrays are flattened.
 *
 * Example:
 *   cn("px-2", isActive && "bg-accent", ["text-sm", disabled && "opacity-50"])
 */

type ClassValue = string | number | false | null | undefined | ClassValue[];

export function cn(...args: ClassValue[]): string {
  const out: string[] = [];
  for (const arg of args) {
    if (!arg) continue;
    if (Array.isArray(arg)) {
      const nested = cn(...arg);
      if (nested) out.push(nested);
    } else if (typeof arg === "string" || typeof arg === "number") {
      out.push(String(arg));
    }
  }
  return out.join(" ");
}
