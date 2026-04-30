// frontend/src/app/products/[id]/page.tsx
import { notFound } from "next/navigation";
import { getProductExperienceReport } from "@/lib/api";
import { ScreenshotGallery } from "@/components/screenshot-gallery";
import { ApiError } from "@/lib/api";

export const dynamic = "force-dynamic";

const PRIORITY_LABEL: Record<string, string> = {
  must: "必备",
  should: "重要",
  nice: "可选",
};
const PRIORITY_STYLE: Record<string, { color: string; bg: string; ring: string }> = {
  must: {
    color: "#8a2525",
    bg: "rgba(181, 51, 51, 0.08)",
    ring: "rgba(181, 51, 51, 0.3)",
  },
  should: {
    color: "#8a6a20",
    bg: "rgba(212, 160, 74, 0.12)",
    ring: "rgba(212, 160, 74, 0.4)",
  },
  nice: {
    color: "#5b6b43",
    bg: "rgba(122, 140, 92, 0.12)",
    ring: "rgba(122, 140, 92, 0.35)",
  },
};

export default async function ProductDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let report;
  try {
    report = await getProductExperienceReport(id);
  } catch (e) {
    if (e instanceof ApiError && (e.code === "PEX001" || e.code === "PEX002")) {
      notFound();
    }
    throw e;
  }

  const features = report.core_features ?? [];
  const featuresByPriority = {
    must: features.filter((f) => f.priority === "must"),
    should: features.filter((f) => f.priority === "should"),
    nice: features.filter((f) => f.priority === "nice" || !f.priority || !["must", "should"].includes(f.priority as string)),
  };

  return (
    <article className="space-y-10" data-testid="product-detail">
      {/* Hero */}
      <header className="space-y-3">
        <h1 className="text-2xl font-medium">{report.product_name}</h1>
        <div className="flex items-center gap-2 flex-wrap">
          {report.project_name && (
            <span
              className="text-[12px] font-mono text-muted-foreground"
              data-testid="product-detail-project-name"
              title="项目英文短名 (project_name)"
            >
              {report.project_name}
            </span>
          )}
          {report.aijuicer_workflow_id && (
            <span
              className="text-[11px] font-medium tracking-wider px-2.5 py-0.5 rounded-md"
              style={{
                color: "#5b6b43",
                background: "rgba(122, 140, 92, 0.12)",
                boxShadow: "0 0 0 1px rgba(122, 140, 92, 0.35)",
              }}
              data-testid="product-detail-aijuicer"
              title={`AIJuicer workflow: ${report.aijuicer_workflow_id}`}
            >
              已入流 AIJuicer
            </span>
          )}
        </div>
        <p className="text-sm text-muted-foreground">
          <a
            href={report.product_url}
            target="_blank"
            rel="noopener noreferrer"
            className="underline"
            data-testid="product-detail-open-original"
          >
            {report.product_url} ↗
          </a>
        </p>
        <div className="flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span>状态: {report.status}</span>
          <span>登录: {report.login_used}</span>
          <span>
            体验分:{" "}
            <span className="text-foreground font-mono">
              {report.overall_ux_score?.toFixed(1) ?? "—"}
            </span>
          </span>
          <span>
            完成于:{" "}
            {report.run_completed_at
              ? new Date(report.run_completed_at).toLocaleString("zh-CN")
              : "—"}
          </span>
        </div>

        {/* 产品理念 —— 最显眼的位置 */}
        {report.product_thesis && (
          <p
            className="mt-4 text-[16px] leading-[1.7] text-foreground border-l-2 pl-4"
            style={{ borderLeftColor: "var(--color-brand)" }}
            data-testid="product-detail-thesis"
          >
            {report.product_thesis}
          </p>
        )}
      </header>

      {report.status === "running" && (
        <section
          className="rounded-md border border-primary/40 bg-primary/5 p-3 text-sm flex items-center gap-3"
          data-testid="product-detail-running"
        >
          <span className="inline-block w-2 h-2 rounded-full bg-primary animate-pulse" />
          Codex 正在体验中，单次大约 5-10 分钟。刷新页面可看进度。
        </section>
      )}

      {report.failure_reason && (
        <section className="rounded-md border border-destructive/40 bg-destructive/5 p-3 text-sm">
          ⚠ 本次运行失败：{report.failure_reason}
        </section>
      )}

      {/* 目标用户画像 */}
      {report.target_user_profile && (
        <section data-testid="product-detail-target-profile">
          <h2 className="text-base font-medium mb-3">目标用户画像</h2>
          <div className="rounded-md border bg-card p-4 space-y-3 text-sm">
            {report.target_user_profile.persona && (
              <div>
                <div className="text-xs text-muted-foreground tracking-wide">人物画像</div>
                <p className="mt-1 leading-relaxed">{report.target_user_profile.persona}</p>
              </div>
            )}
            {report.target_user_profile.scenarios?.length > 0 && (
              <div>
                <div className="text-xs text-muted-foreground tracking-wide">典型场景</div>
                <ul className="mt-1 space-y-1 list-disc list-inside">
                  {report.target_user_profile.scenarios.map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
            {report.target_user_profile.pain_points?.length > 0 && (
              <div>
                <div className="text-xs text-muted-foreground tracking-wide">原本的痛点</div>
                <ul className="mt-1 space-y-1 list-disc list-inside">
                  {report.target_user_profile.pain_points.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </div>
            )}
            {report.target_user_profile.why_this_product && (
              <div>
                <div className="text-xs text-muted-foreground tracking-wide">为什么选这个产品</div>
                <p className="mt-1 leading-relaxed">{report.target_user_profile.why_this_product}</p>
              </div>
            )}
          </div>
        </section>
      )}

      {/* 核心功能 含设计意图 */}
      {features.length > 0 && (
        <section data-testid="product-detail-core-features">
          <h2 className="text-base font-medium mb-3">核心功能（含设计意图）</h2>
          <div className="space-y-4">
            {(["must", "should", "nice"] as const).map((p) =>
              featuresByPriority[p].length === 0 ? null : (
                <div key={p}>
                  <div className="flex items-center gap-2 mb-2">
                    <span
                      className="text-[11px] font-medium tracking-wider px-2 py-0.5 rounded-md"
                      style={{
                        color: PRIORITY_STYLE[p].color,
                        background: PRIORITY_STYLE[p].bg,
                        boxShadow: `0 0 0 1px ${PRIORITY_STYLE[p].ring}`,
                      }}
                    >
                      {PRIORITY_LABEL[p]}
                    </span>
                    <span className="text-xs text-muted-foreground">
                      {featuresByPriority[p].length} 项
                    </span>
                  </div>
                  <ul className="space-y-2 text-sm">
                    {featuresByPriority[p].map((f, i) => (
                      <li
                        key={i}
                        className="border-l-2 pl-3 py-1"
                        style={{ borderLeftColor: PRIORITY_STYLE[p].ring }}
                      >
                        <div className="font-medium">{f.name}</div>
                        {f.where_seen && (
                          <div className="text-xs text-muted-foreground mt-0.5">
                            {f.where_seen}
                          </div>
                        )}
                        {f.rationale && (
                          <p className="text-xs leading-relaxed mt-1.5 text-foreground/80">
                            <span className="text-muted-foreground">设计意图：</span>
                            {f.rationale}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
              ),
            )}
          </div>
        </section>
      )}

      {/* 创新切入点 */}
      {report.innovation_angles && report.innovation_angles.length > 0 && (
        <section data-testid="product-detail-innovation">
          <h2 className="text-base font-medium mb-3">创新切入点</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {report.innovation_angles.map((a, i) => (
              <div key={i} className="rounded-md border bg-card p-4">
                <div className="text-sm font-medium text-primary">{a.angle}</div>
                {a.hypothesis && (
                  <p className="mt-2 text-sm leading-relaxed">{a.hypothesis}</p>
                )}
                {a.examples?.length > 0 && (
                  <ul className="mt-2 space-y-1 text-xs text-muted-foreground list-disc list-inside">
                    {a.examples.map((ex, j) => (
                      <li key={j}>{ex}</li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 差异化机会 */}
      {report.differentiation_opportunities && report.differentiation_opportunities.length > 0 && (
        <section data-testid="product-detail-differentiation">
          <h2 className="text-base font-medium mb-3">差异化机会</h2>
          <div className="space-y-3">
            {report.differentiation_opportunities.map((d, i) => (
              <div key={i} className="rounded-md border bg-card p-4">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-sm">
                  <div>
                    <div className="text-xs text-muted-foreground tracking-wide mb-1">观察</div>
                    <p className="leading-relaxed">{d.observation}</p>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground tracking-wide mb-1">机会</div>
                    <p className="leading-relaxed">{d.opportunity ?? "—"}</p>
                  </div>
                </div>
                {d.why_it_matters && (
                  <p className="mt-3 text-xs leading-relaxed text-foreground/80 pt-3 border-t">
                    <span className="text-muted-foreground">为什么有价值：</span>
                    {d.why_it_matters}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      )}

      {/* 商业模式参考 */}
      {report.monetization_model && (
        <Section title="商业模式参考">{report.monetization_model}</Section>
      )}

      {/* 截图 */}
      <section>
        <h2 className="text-base font-medium mb-3">截图</h2>
        <ScreenshotGallery shots={report.screenshots ?? []} />
      </section>

      {/* 附录：旧字段 + 推理轨迹 */}
      <details className="rounded-md border bg-card p-4 text-sm">
        <summary className="cursor-pointer text-muted-foreground">
          附录：原始体验数据（兼容旧报告）
        </summary>
        <div className="mt-4 space-y-5">
          {report.summary_zh && <Section title="概览">{report.summary_zh}</Section>}
          {report.feature_inventory && report.feature_inventory.length > 0 && (
            <section>
              <h3 className="text-sm font-medium mb-2">功能盘点</h3>
              <ul className="space-y-1 text-xs">
                {report.feature_inventory.map((f, i) => (
                  <li key={i}>
                    <span className="font-medium">{f.name}</span>
                    {f.where_found && (
                      <span className="text-muted-foreground"> · {f.where_found}</span>
                    )}
                    {f.notes && <span className="text-muted-foreground"> · {f.notes}</span>}
                  </li>
                ))}
              </ul>
            </section>
          )}
          {report.strengths && <Section title="优点">{report.strengths}</Section>}
          {report.weaknesses && <Section title="缺点">{report.weaknesses}</Section>}
          {report.target_user && <Section title="目标用户（旧）">{report.target_user}</Section>}
          {report.agent_trace && (
            <section>
              <h3 className="text-sm font-medium mb-2">Agent 推理轨迹</h3>
              <pre
                className="text-[11px] bg-muted p-3 rounded-md overflow-x-auto"
                data-testid="product-detail-trace"
              >
                {(() => {
                  try {
                    return JSON.stringify(report.agent_trace, null, 2);
                  } catch {
                    return "（轨迹数据损坏）";
                  }
                })()}
              </pre>
            </section>
          )}
        </div>
      </details>
    </article>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-base font-medium mb-2">{title}</h2>
      <p className="text-sm leading-relaxed whitespace-pre-line">{children}</p>
    </section>
  );
}
