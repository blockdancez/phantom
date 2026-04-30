"use client";

import { HistoryEntry, stepLabel } from "@/lib/api";

const APPROVAL_LABEL: Record<string, { label: string; tone: string }> = {
  approve: { label: "批准", tone: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  approved: { label: "批准", tone: "border-emerald-200 bg-emerald-50 text-emerald-700" },
  reject: { label: "拒绝", tone: "border-rose-200 bg-rose-50 text-rose-700" },
  rerun: { label: "重新执行", tone: "border-amber-200 bg-amber-50 text-amber-700" },
  abort: { label: "中止", tone: "border-slate-200 bg-slate-100 text-slate-700" },
  skip: { label: "跳过", tone: "border-slate-200 bg-slate-100 text-slate-700" },
};

function fmt(t: string): string {
  return new Date(t).toLocaleString();
}

export function HistoryPanel({ entries }: { entries: HistoryEntry[] }) {
  if (entries.length === 0) {
    return (
      <div className="px-4 py-8 text-center text-sm text-slate-400">暂无历史记录</div>
    );
  }
  return (
    <ul className="divide-y divide-slate-100">
      {entries.map((e, i) => {
        if (e.kind === "approval") {
          const meta = APPROVAL_LABEL[e.decision] ?? {
            label: e.decision,
            tone: "border-slate-200 bg-slate-100 text-slate-700",
          };
          return (
            <li key={`a-${i}`} className="flex items-start gap-3 px-4 py-3 text-sm">
              <span className={`badge shrink-0 ${meta.tone}`}>{meta.label}</span>
              <div className="min-w-0 flex-1">
                <div className="font-medium">
                  {stepLabel(e.step)}
                  <span className="ml-2 font-mono text-xs text-slate-400">{e.step}</span>
                </div>
                {e.comment && (
                  <div className="mt-0.5 whitespace-pre-wrap text-xs text-slate-600">
                    {e.comment}
                  </div>
                )}
              </div>
              <span className="shrink-0 text-xs text-slate-400">{fmt(e.created_at)}</span>
            </li>
          );
        }
        // artifact_edited
        return (
          <li key={`e-${i}`} className="flex items-start gap-3 px-4 py-3 text-sm">
            <span className="badge shrink-0 border-blue-200 bg-blue-50 text-blue-700">
              编辑产物
            </span>
            <div className="min-w-0 flex-1">
              <div className="font-medium">
                {stepLabel(e.step ?? null)}
                <span className="ml-2 font-mono text-xs text-slate-400">
                  {e.step}/{e.key}
                </span>
              </div>
              {e.comment && (
                <div className="mt-0.5 whitespace-pre-wrap text-xs text-slate-600">
                  {e.comment}
                </div>
              )}
            </div>
            <span className="shrink-0 text-xs text-slate-400">{fmt(e.created_at)}</span>
          </li>
        );
      })}
    </ul>
  );
}
