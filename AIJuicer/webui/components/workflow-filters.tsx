"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { STATUS_GROUPS } from "@/lib/api";

export function WorkflowFilters() {
  const router = useRouter();
  const sp = useSearchParams();
  const [q, setQ] = useState(sp.get("q") ?? "");
  const [group, setGroup] = useState(sp.get("status_group") ?? "");

  function apply(next: { q?: string; group?: string; page?: number }) {
    const params = new URLSearchParams();
    const qv = next.q !== undefined ? next.q : q;
    const gv = next.group !== undefined ? next.group : group;
    if (qv) params.set("q", qv);
    if (gv) params.set("status_group", gv);
    if (next.page && next.page > 1) params.set("page", String(next.page));
    // 任何筛选条件改变都重置到第 1 页
    const qs = params.toString();
    router.push(qs ? `/workflows?${qs}` : "/workflows");
  }

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    apply({ q, group });
  }

  function onReset() {
    setQ("");
    setGroup("");
    router.push("/workflows");
  }

  return (
    <form onSubmit={onSubmit} className="card flex flex-wrap items-center gap-2 p-3 text-sm">
      <input
        type="text"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="按项目标题搜索（不区分大小写）"
        className="min-w-[260px] flex-1 rounded-md border border-slate-300 px-3 py-1.5"
      />
      <select
        value={group}
        onChange={(e) => {
          setGroup(e.target.value);
          apply({ group: e.target.value });
        }}
        className="rounded-md border border-slate-300 bg-white px-2 py-1.5"
      >
        {STATUS_GROUPS.map((g) => (
          <option key={g.value} value={g.value}>
            {g.label}
          </option>
        ))}
      </select>
      <button type="submit" className="btn btn-primary">
        搜索
      </button>
      <button type="button" className="btn" onClick={onReset}>
        清空
      </button>
    </form>
  );
}
