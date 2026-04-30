import { AgentInfo, listAgents, STEPS, stepLabel } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function AgentsPage() {
  let items: AgentInfo[] = [];
  let err: string | null = null;
  try {
    items = await listAgents();
  } catch (e: any) {
    err = e.message ?? String(e);
  }

  const grouped = STEPS.map((s) => ({
    step: s,
    items: items.filter((a) => a.step === s),
  }));

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Agent 列表</h1>
      {err && <div className="rounded bg-rose-50 px-3 py-2 text-sm text-rose-700">{err}</div>}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        {grouped.map((g) => (
          <div key={g.step} className="card p-4">
            <h2 className="text-sm font-semibold">
              {stepLabel(g.step)}
              <span className="ml-1 font-mono text-xs text-slate-400">{g.step}</span>
            </h2>
            {g.items.length === 0 ? (
              <div className="mt-2 text-xs text-slate-400">暂无注册的 agent</div>
            ) : (
              <ul className="mt-2 space-y-2 text-sm">
                {g.items.map((a) => {
                  const addr =
                    a.host && a.port ? `${a.host}:${a.port}` : "—";
                  const healthUrl =
                    a.host && a.port ? `http://${a.host}:${a.port}/health` : null;
                  return (
                    <li
                      key={a.id}
                      className="flex items-start justify-between gap-2"
                    >
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="truncate font-medium">{a.name}</span>
                          <span
                            className={
                              a.status === "online"
                                ? "badge border-emerald-200 bg-emerald-50 text-emerald-700"
                                : a.status === "offline"
                                  ? "badge border-rose-200 bg-rose-50 text-rose-700"
                                  : "badge border-slate-200 bg-slate-100 text-slate-600"
                            }
                            title={`last_seen_at: ${a.last_seen_at}`}
                          >
                            <span
                              className={
                                "mr-1 inline-block h-1.5 w-1.5 rounded-full " +
                                (a.status === "online"
                                  ? "bg-emerald-500"
                                  : a.status === "offline"
                                    ? "bg-rose-500"
                                    : "bg-slate-400")
                              }
                            />
                            {a.status === "online"
                              ? "在线"
                              : a.status === "offline"
                                ? "离线"
                                : a.status}
                          </span>
                        </div>
                        <div className="mt-0.5 font-mono text-xs text-slate-500">
                          {healthUrl ? (
                            <a
                              href={healthUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="hover:text-brand-600 hover:underline"
                              title="点击查看 /health"
                            >
                              {addr}
                            </a>
                          ) : (
                            <span>{addr}</span>
                          )}
                          {a.pid ? (
                            <span className="ml-2 text-slate-400">
                              pid={a.pid}
                            </span>
                          ) : null}
                        </div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
