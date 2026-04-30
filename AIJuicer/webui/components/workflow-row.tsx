"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { Workflow, deleteWorkflow, statusLabel, stepLabel } from "@/lib/api";
import { JuicerSpinner } from "@/components/juicer-spinner";

function statusTone(s: string): string {
  if (s === "COMPLETED") return "bg-emerald-50 text-emerald-700 border-emerald-200";
  if (s === "ABORTED") return "bg-rose-50 text-rose-700 border-rose-200";
  if (s === "AWAITING_MANUAL_ACTION") return "bg-amber-50 text-amber-800 border-amber-200";
  if (s.startsWith("AWAITING_APPROVAL")) return "bg-sky-50 text-sky-800 border-sky-200";
  if (s.endsWith("_RUNNING")) return "bg-indigo-50 text-indigo-800 border-indigo-200";
  return "bg-slate-50 text-slate-700 border-slate-200";
}

export function WorkflowRow({ w }: { w: Workflow }) {
  const router = useRouter();
  const [isPending, start] = useTransition();
  const [busy, setBusy] = useState(false);

  async function onDelete() {
    if (!confirm(`确定删除工作流"${w.name}"吗？此操作不可恢复。`)) return;
    setBusy(true);
    try {
      await deleteWorkflow(w.id);
      start(() => router.refresh());
    } catch (e: any) {
      alert(`删除失败：${e.message ?? e}`);
    } finally {
      setBusy(false);
    }
  }

  const running = w.status.endsWith("_RUNNING");

  return (
    <tr className="border-b border-slate-100 last:border-0 hover:bg-slate-50">
      <td className="px-4 py-2 font-medium">
        <Link href={`/workflows/${w.id}`} className="text-brand-600 hover:underline">
          {w.name}
        </Link>
        {w.project_name && (
          <div className="mt-0.5 font-mono text-[11px] text-slate-400">
            {w.project_name}
          </div>
        )}
      </td>
      <td className="px-4 py-2">
        <span
          className={`badge border gap-1.5 ${statusTone(w.status)}`}
          style={{ fontVariantNumeric: "tabular-nums" }}
        >
          {running && <JuicerSpinner size={14} />}
          {statusLabel(w.status)}
        </span>
      </td>
      <td className="px-4 py-2 text-slate-600">{stepLabel(w.current_step)}</td>
      <td className="px-4 py-2 text-slate-500">
        {new Date(w.created_at).toLocaleString()}
      </td>
      <td className="px-4 py-2 text-right">
        <button
          onClick={onDelete}
          disabled={busy || isPending}
          className="btn btn-danger px-2 py-0.5 text-xs"
          title="删除工作流"
        >
          {busy ? "删除中…" : "删除"}
        </button>
      </td>
    </tr>
  );
}
