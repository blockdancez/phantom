"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { ApiError, triggerJob } from "@/lib/api";

interface Props {
  jobId: string;
  label: string;
}

type State = "idle" | "loading" | "done" | "error";

export function TriggerButton({ jobId, label }: Props) {
  const router = useRouter();
  const [, startTransition] = useTransition();
  const [state, setState] = useState<State>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handle() {
    if (state === "loading") return;
    setState("loading");
    setErrorMessage(null);
    try {
      await triggerJob(jobId);
      setState("done");
      // Re-fetch server components so the pipeline card shows the new
      // next_run_time and, after the job actually runs, the updated counts.
      startTransition(() => router.refresh());
      setTimeout(() => setState("idle"), 1800);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? `[${err.code}] ${err.message}`
          : err instanceof Error
            ? err.message
            : "请求失败";
      setErrorMessage(msg);
      setState("error");
      setTimeout(() => setState("idle"), 3000);
    }
  }

  const text =
    state === "loading"
      ? "触发中…"
      : state === "done"
        ? "已触发 ✓"
        : state === "error"
          ? "失败"
          : `立即${label}`;

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
    <div className="flex flex-col items-end gap-1">
      <button
        type="button"
        onClick={handle}
        disabled={state === "loading"}
        className="text-[11px] font-medium tracking-tight px-2.5 py-1 rounded-md transition-all disabled:opacity-70 hover:brightness-95"
        style={style}
        data-testid={`dashboard-trigger-${jobId}`}
        data-state={state}
        aria-label={`触发${label}任务`}
      >
        {text}
      </button>
      {state === "error" && errorMessage && (
        <p
          className="text-[10px] text-destructive/80 font-serif italic max-w-[180px] text-right"
          data-testid={`dashboard-trigger-${jobId}-error`}
        >
          {errorMessage}
        </p>
      )}
    </div>
  );
}
