"use client";

import { JuicerSpinner } from "@/components/juicer-spinner";

export type TimelineEntry = {
  time: string;
  event_type: string;
  payload?: Record<string, unknown>;
  request_id?: string | null;
};

export function Timeline({ entries }: { entries: TimelineEntry[] }) {
  if (entries.length === 0) {
    return <JuicerSpinner size={18} label="等待事件中…" />;
  }
  return (
    <ol className="space-y-1 text-xs">
      {entries.map((e, i) => (
        <li key={i} className="flex gap-3 rounded px-2 py-1 hover:bg-slate-50">
          <span className="shrink-0 font-mono text-slate-400">
            {new Date(e.time).toLocaleTimeString()}
          </span>
          <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-700">
            {e.event_type}
          </span>
          <span className="truncate text-slate-600">
            {summarizePayload(e.payload)}
          </span>
        </li>
      ))}
    </ol>
  );
}

function summarizePayload(p?: Record<string, unknown>): string {
  if (!p) return "";
  if (p.from && p.to) return `${p.from} → ${p.to}`;
  if (p.step && p.task_id) return `${p.step} · task=${String(p.task_id).slice(0, 8)}`;
  if (p.name) return String(p.name);
  return JSON.stringify(p).slice(0, 140);
}
