"use client";

import { useState } from "react";

interface Props {
  text: string;
  label?: string;
  className?: string;
  "data-testid"?: string;
  "aria-label"?: string;
}

export function CopyButton({
  text,
  label = "复制",
  className = "",
  "data-testid": testId,
  "aria-label": ariaLabel,
}: Props) {
  const [state, setState] = useState<"idle" | "done" | "error">("idle");

  async function handle(e: React.MouseEvent) {
    // If this button lives inside a <summary>, clicking it would toggle the
    // parent <details>. Stop both so the button only copies.
    e.preventDefault();
    e.stopPropagation();

    try {
      await navigator.clipboard.writeText(text);
      setState("done");
    } catch {
      setState("error");
    }
    setTimeout(() => setState("idle"), 1800);
  }

  const display =
    state === "done" ? "已复制 ✓" : state === "error" ? "复制失败" : label;

  const style =
    state === "done"
      ? {
          color: "#5b6b43",
          background: "rgba(122, 140, 92, 0.14)",
          boxShadow: "0 0 0 1px rgba(122, 140, 92, 0.4)",
        }
      : state === "error"
        ? {
            color: "#8a2525",
            background: "rgba(181, 51, 51, 0.08)",
            boxShadow: "0 0 0 1px rgba(181, 51, 51, 0.35)",
          }
        : {
            color: "var(--color-brand)",
            background: "rgba(201, 100, 66, 0.08)",
            boxShadow: "0 0 0 1px rgba(201, 100, 66, 0.3)",
          };

  return (
    <button
      type="button"
      onClick={handle}
      className={`text-[11px] font-medium tracking-tight px-2.5 py-1 rounded-md transition-all hover:brightness-95 ${className}`}
      style={style}
      aria-label={ariaLabel ?? label}
      data-testid={testId}
    >
      {display}
    </button>
  );
}
