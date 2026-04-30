import Link from "next/link";
import {
  DashboardSummary,
  STEPS,
  getDashboardSummary,
  statusLabel,
  stepLabel,
} from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  let data: DashboardSummary | null = null;
  let error: string | null = null;
  try {
    data = await getDashboardSummary();
  } catch (e: any) {
    error = e.message ?? String(e);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">主页</h1>
        <div className="flex gap-2">
          <Link href="/workflows" className="btn">
            查看全部工作流
          </Link>
          <Link href="/workflows/new" className="btn btn-primary">
            + 新建工作流
          </Link>
        </div>
      </div>

      {error && (
        <div className="card border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          加载概览失败：{error}
        </div>
      )}

      {data && (
        <>
          {/* 顶部状态汇总 */}
          <div className="grid grid-cols-2 gap-3 md:grid-cols-6">
            <KpiCard label="进行中" value={data.totals.running} tone="indigo" />
            <KpiCard label="等待审批" value={data.totals.awaiting} tone="blue" />
            <KpiCard label="需人工介入" value={data.totals.manual} tone="rose" />
            <KpiCard label="已完成" value={data.totals.completed} tone="emerald" />
            <KpiCard label="已中止" value={data.totals.aborted} tone="slate" />
            <KpiCard label="总计" value={data.totals.total} tone="slate" />
          </div>

          {/* 待办事项 */}
          <section className="card overflow-hidden">
            <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
              <h2 className="text-sm font-semibold">
                待办事项
                <span className="ml-2 text-xs text-slate-400">
                  共 {data.pending.length} 项
                </span>
              </h2>
            </div>
            {data.pending.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-slate-400">
                没有待你处理的工作流 🎉
              </div>
            ) : (
              <ul className="divide-y divide-slate-100">
                {data.pending.map((w) => (
                  <li key={w.id} className="flex items-center justify-between px-4 py-3 text-sm">
                    <div className="min-w-0 flex-1">
                      <Link
                        href={`/workflows/${w.id}`}
                        className="block truncate font-medium hover:text-brand-700"
                      >
                        {w.name}
                      </Link>
                      <div className="mt-0.5 flex items-center gap-2 text-xs text-slate-500">
                        <span className="font-mono">{w.id.slice(0, 8)}</span>
                        <span>·</span>
                        <span>更新于 {new Date(w.updated_at).toLocaleString()}</span>
                      </div>
                    </div>
                    <div className="ml-3 flex items-center gap-2">
                      <span
                        className={`badge ${
                          w.status === "AWAITING_MANUAL_ACTION"
                            ? "border-rose-200 bg-rose-50 text-rose-700"
                            : "border-blue-200 bg-blue-50 text-blue-700"
                        }`}
                      >
                        {statusLabel(w.status)}
                      </span>
                      <Link href={`/workflows/${w.id}`} className="btn btn-primary py-0.5 text-xs">
                        去处理 →
                      </Link>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </section>

          {/* 各步骤状态分布 */}
          <section className="card overflow-hidden">
            <div className="border-b border-slate-200 px-4 py-3">
              <h2 className="text-sm font-semibold">各步骤状态分布</h2>
            </div>
            <table className="w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-4 py-2">步骤</th>
                  <th className="px-4 py-2 text-right">进行中</th>
                  <th className="px-4 py-2 text-right">待审批</th>
                  <th className="px-4 py-2 text-right">失败</th>
                  <th className="px-4 py-2 text-right">已完成</th>
                </tr>
              </thead>
              <tbody>
                {STEPS.map((step) => {
                  const g = data!.grid[step] ?? {
                    running: 0,
                    awaiting: 0,
                    failed: 0,
                    done: 0,
                  };
                  return (
                    <tr key={step} className="border-t border-slate-100">
                      <td className="px-4 py-2">
                        {stepLabel(step)}
                        <span className="ml-2 font-mono text-xs text-slate-400">{step}</span>
                      </td>
                      <Cell n={g.running} tone="indigo" stepFilter={step} />
                      <Cell n={g.awaiting} tone="blue" stepFilter={step} />
                      <Cell n={g.failed} tone="rose" stepFilter={step} />
                      <Cell n={g.done} tone="emerald" stepFilter={step} />
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  );
}

const TONE_CLS: Record<string, { fg: string; ring: string }> = {
  indigo: { fg: "text-indigo-700", ring: "ring-indigo-100" },
  blue: { fg: "text-blue-700", ring: "ring-blue-100" },
  rose: { fg: "text-rose-700", ring: "ring-rose-100" },
  emerald: { fg: "text-emerald-700", ring: "ring-emerald-100" },
  slate: { fg: "text-slate-700", ring: "ring-slate-100" },
};

function KpiCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: keyof typeof TONE_CLS;
}) {
  const t = TONE_CLS[tone];
  return (
    <div className={`card flex flex-col px-4 py-3 ring-1 ${t.ring}`}>
      <span className="text-xs text-slate-500">{label}</span>
      <span className={`mt-0.5 text-2xl font-semibold ${t.fg}`}>{value}</span>
    </div>
  );
}

function Cell({
  n,
  tone,
}: {
  n: number;
  tone: keyof typeof TONE_CLS;
  stepFilter?: string;
}) {
  if (n === 0) {
    return <td className="px-4 py-2 text-right text-slate-300">0</td>;
  }
  const t = TONE_CLS[tone];
  return (
    <td className="px-4 py-2 text-right">
      <span className={`font-semibold ${t.fg}`}>{n}</span>
    </td>
  );
}
