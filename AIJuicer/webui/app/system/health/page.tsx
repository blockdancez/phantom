import { API_BASE, getSystemStatus, stepLabel, SystemStatus } from "@/lib/api";

export const dynamic = "force-dynamic";

async function probe(path: string): Promise<{ ok: boolean; body: string }> {
  try {
    const r = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    return { ok: r.ok, body: (await r.text()).slice(0, 4000) };
  } catch (e: any) {
    return { ok: false, body: e.message ?? String(e) };
  }
}

function fmtUptime(sec?: number): string {
  if (!sec) return "—";
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function fmtIdle(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m${s % 60}s`;
}

export default async function Health() {
  const [health, status] = await Promise.all([
    probe("/health"),
    getSystemStatus().catch((e: any): null => {
      console.error(e);
      return null;
    }),
  ]);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">系统状态</h1>

      <div className="card p-4">
        <div className="mb-2 text-sm font-semibold">
          Scheduler /health {health.ok ? "✅" : "❌"}
        </div>
        <pre className="code">{health.body || "(空)"}</pre>
      </div>

      {/* Redis 信息 */}
      <div className="card p-4">
        <div className="mb-3 flex items-center justify-between">
          <div className="text-sm font-semibold">
            Redis {status?.redis.ping ? "✅" : "❌"}
          </div>
          {status?.redis.ping && (
            <span className="text-xs text-slate-500">
              ping {status.redis.ping_ms}ms
            </span>
          )}
        </div>
        {status ? (
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <KV k="URL" v={<span className="font-mono text-xs">{status.redis.url}</span>} />
            <KV k="版本" v={status.redis.version} />
            <KV k="模式" v={status.redis.mode} />
            <KV k="运行时长" v={fmtUptime(status.redis.uptime_sec)} />
            <KV k="已用内存" v={status.redis.used_memory_human} />
            <KV k="活跃连接" v={status.redis.connected_clients} />
            <KV k="累计命令" v={status.redis.total_commands_processed?.toLocaleString()} />
          </dl>
        ) : (
          <div className="text-sm text-slate-400">无法获取 Redis 状态</div>
        )}
      </div>

      {/* 每个 step 的队列 */}
      <div className="card p-4">
        <div className="mb-3 text-sm font-semibold">任务队列（按步骤）</div>
        {status ? (
          <div className="overflow-hidden rounded border border-slate-200">
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-500">
                <tr>
                  <th className="px-3 py-2">步骤</th>
                  <th className="px-3 py-2">Stream</th>
                  <th className="px-3 py-2 text-right">队列深度</th>
                  <th className="px-3 py-2 text-right">未确认</th>
                  <th className="px-3 py-2 text-right">在线 Agent</th>
                  <th className="px-3 py-2">消费者</th>
                </tr>
              </thead>
              <tbody>
                {status.steps.map((s: SystemStatus["steps"][number]) => (
                  <tr key={s.step} className="border-b border-slate-100 last:border-0">
                    <td className="px-3 py-2">
                      {stepLabel(s.step)}
                      <span className="ml-1 font-mono text-xs text-slate-400">{s.step}</span>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs text-slate-500">{s.stream}</td>
                    <td className="px-3 py-2 text-right">
                      <span
                        className={
                          s.stream_length > 0
                            ? "font-semibold text-amber-700"
                            : "text-slate-500"
                        }
                      >
                        {s.stream_length}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span
                        className={
                          s.pending > 0 ? "font-semibold text-rose-700" : "text-slate-500"
                        }
                      >
                        {s.pending}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      <span
                        className={
                          s.agents_online > 0
                            ? "font-semibold text-emerald-700"
                            : "text-slate-400"
                        }
                      >
                        {s.agents_online}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {s.consumers.length === 0 ? (
                        <span className="text-xs text-slate-400">—</span>
                      ) : (
                        <div className="space-y-1">
                          {s.consumers.map((c) => (
                            <div
                              key={c.name}
                              className="flex items-center gap-2 text-xs text-slate-600"
                            >
                              <span className="truncate font-mono">{c.name}</span>
                              <span className="text-slate-400">
                                pending={c.pending}
                              </span>
                              <span className="text-slate-400">
                                idle={fmtIdle(c.idle_ms)}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="text-sm text-slate-400">无法获取队列状态</div>
        )}
      </div>

      <div className="text-xs text-slate-500">
        后端地址：<span className="font-mono">{API_BASE}</span>
      </div>
    </div>
  );
}

function KV({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{k}</dt>
      <dd className="font-medium">{v ?? "—"}</dd>
    </div>
  );
}
