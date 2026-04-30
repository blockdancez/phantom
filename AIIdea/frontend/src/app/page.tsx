import Link from "next/link";
import {
  getSourceItems,
  getAnalysisResults,
  getSourceStats,
  getPipelineStatus,
  getHealth,
  listProductExperienceReports,
} from "@/lib/api";
import { ScoreIndicator } from "@/components/score-indicator";
import { TriggerButton } from "@/components/trigger-button";
import { formatRelative, formatFutureRelative } from "@/lib/utils";
import type {
  SourceItemList,
  AnalysisResultList,
  SourceStatsList,
  PipelineStatus,
  HealthStatus,
  ProductExperienceListResponse,
} from "@/lib/types";

const JOB_LABELS: Record<string, string> = {
  collect_data: "采集数据",
  process_data: "处理数据",
  analyze_data: "分析 IDEA",
  discover_products: "发现产品",
  experience_products: "体验产品",
};

const DASHBOARD_JOB_IDS = [
  "collect_data",
  "process_data",
  "analyze_data",
  "discover_products",
  "experience_products",
] as const;

const EXPERIENCE_STATUS_LABELS: Record<string, string> = {
  completed: "完成",
  partial: "部分完成",
  failed: "失败",
};

const EXPERIENCE_LOGIN_LABELS: Record<string, string> = {
  google: "Google 登录",
  none: "未登录",
  failed: "登录失败",
  skipped: "未尝试登录",
};

export default async function DashboardPage() {
  let sourceData: SourceItemList | null = null;
  let analysisData: AnalysisResultList | null = null;
  let sourceStats: SourceStatsList | null = null;
  let pipeline: PipelineStatus | null = null;
  let experiences: ProductExperienceListResponse | null = null;
  let health: HealthStatus | null = null;
  let error: string | null = null;

  try {
    [sourceData, analysisData, sourceStats, pipeline, experiences] =
      await Promise.all([
        getSourceItems({ page: 1, per_page: 6 }),
        getAnalysisResults({ page: 1, per_page: 3 }),
        getSourceStats(),
        getPipelineStatus(),
        listProductExperienceReports({ page: 1, per_page: 3 }),
      ]);
  } catch {
    error = "无法连接到后端服务，请确认 API 已启动。";
  }

  // Health is fetched independently so a DB blip (which surfaces as 503 on
  // /api/health) doesn't poison the whole dashboard — we still want to show
  // stats from cached data where possible.
  try {
    health = await getHealth();
  } catch {
    health = { status: "fail", db: "fail", scheduler: "fail" };
  }

  const headline = [
    { label: "已采集数据", value: pipeline?.total_items },
    { label: "数据源数量", value: pipeline?.distinct_sources },
    { label: "创意 IDEA", value: pipeline?.analysis_count },
  ];

  const processedPct =
    pipeline && pipeline.total_items > 0
      ? Math.round((pipeline.processed_items / pipeline.total_items) * 100)
      : 0;

  return (
    <div
      className="max-w-6xl mx-auto space-y-12"
      data-testid="dashboard-page"
    >
      <header>
        <p className="text-[11px] font-medium tracking-[0.2em] text-muted-foreground">
          今日简报
        </p>
        <h1 className="font-serif text-[44px] text-foreground mt-2 leading-[1.15]">
          细读全网的微弱信号
        </h1>
        <p className="text-[16px] text-muted-foreground mt-3 max-w-2xl leading-relaxed">
          持续搜集来自发布站、论文库与社区的讨论，统一打分与归纳，帮助你第一时间看见值得停留的线索。
        </p>
      </header>

      {/* Health status row — feature-8 plan requires health + scheduler badge on top */}
      <section
        className="flex flex-wrap items-center gap-3"
        data-testid="dashboard-health-row"
        aria-label="服务健康状态"
      >
        <HealthBadge label="服务" status={health?.status ?? "fail"} testId="dashboard-health-status" />
        <HealthBadge label="数据库" status={health?.db ?? "fail"} testId="dashboard-health-db" />
        <HealthBadge label="调度器" status={health?.scheduler ?? "fail"} testId="dashboard-health-scheduler" />
      </section>

      {error && (
        <div
          className="rounded-xl px-5 py-4 text-[13.5px] text-foreground"
          data-testid="dashboard-error"
          style={{
            background: "rgba(212, 160, 74, 0.1)",
            boxShadow: "0 0 0 1px rgba(212, 160, 74, 0.3)",
          }}
        >
          {error}
        </div>
      )}

      {/* Headline metrics */}
      <section className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {headline.map((stat) => (
          <div
            key={stat.label}
            className="rounded-2xl bg-card px-6 py-5"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            <p className="text-[11px] font-medium text-muted-foreground tracking-[0.15em]">
              {stat.label}
            </p>
            <p className="font-serif text-[40px] text-foreground mt-2 leading-none tabular-nums">
              {stat.value ?? "—"}
            </p>
          </div>
        ))}
      </section>

      {/* Pipeline status */}
      {pipeline && (
        <section>
          <div className="flex items-baseline justify-between mb-5">
            <h2 className="font-serif text-[26px] text-foreground">数据管线</h2>
            <p className="text-[12px] text-muted-foreground font-serif italic">
              采集 → 处理 → 分析
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Processing progress */}
            <div
              className="rounded-2xl bg-card px-6 py-5"
              style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
            >
              <div className="flex items-baseline justify-between">
                <p className="text-[11px] font-medium text-muted-foreground tracking-[0.15em]">
                  处理进度
                </p>
                <p className="text-[12px] text-muted-foreground font-serif italic tabular-nums">
                  {pipeline.processed_items} / {pipeline.total_items}
                </p>
              </div>
              <p className="font-serif text-[32px] text-foreground mt-2 leading-none tabular-nums">
                {processedPct}
                <span className="text-[20px] text-muted-foreground ml-1">%</span>
              </p>
              <div
                className="h-1.5 rounded-full mt-4 overflow-hidden"
                style={{ background: "rgba(201, 100, 66, 0.1)" }}
              >
                <div
                  className="h-full bg-primary rounded-full transition-all"
                  style={{ width: `${processedPct}%` }}
                />
              </div>
              <p className="text-[11px] text-muted-foreground mt-3 font-serif italic">
                {pipeline.unprocessed_items} 条待处理
              </p>
            </div>

            {/* Last runs */}
            <div
              className="rounded-2xl bg-card px-6 py-5"
              style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
            >
              <p className="text-[11px] font-medium text-muted-foreground tracking-[0.15em]">
                最近活动
              </p>
              <div className="mt-3 space-y-2.5">
                <div className="flex items-baseline justify-between text-[13px]">
                  <span className="text-muted-foreground">最近采集</span>
                  <span className="text-foreground font-serif italic">
                    {formatRelative(pipeline.last_collected_at)}
                  </span>
                </div>
                <div className="flex items-baseline justify-between text-[13px]">
                  <span className="text-muted-foreground">最近分析</span>
                  <span className="text-foreground font-serif italic">
                    {formatRelative(pipeline.last_analysis_at)}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Scheduled jobs */}
          {pipeline.jobs.length > 0 && (
            <div className="mt-4 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              {DASHBOARD_JOB_IDS.map((id) => {
                const job = pipeline.jobs.find((j) => j.id === id);
                if (!job) return null;
                const label = JOB_LABELS[id];
                return (
                  <div
                    key={id}
                    className="rounded-xl bg-card px-4 py-3 flex flex-col"
                    style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
                    data-testid={`dashboard-job-card-${id}`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] font-medium text-primary tracking-[0.12em]">
                        {label}
                      </span>
                      <span
                        className="w-1.5 h-1.5 rounded-full animate-pulse"
                        style={{ background: "var(--color-success)" }}
                      />
                    </div>
                    <p className="text-[14px] text-foreground font-serif mt-2">
                      {formatFutureRelative(job.next_run_time)}
                    </p>
                    <p className="text-[10px] text-muted-foreground mt-1 font-serif italic">
                      {job.trigger.replace("interval[", "每 ").replace("]", "")}
                    </p>
                    <div className="mt-3 flex justify-end">
                      <TriggerButton jobId={id} label={label} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      )}

      {/* Product experience overview */}
      {experiences && (
        <section data-testid="dashboard-experience-section">
          <div className="flex items-baseline justify-between mb-5">
            <h2 className="font-serif text-[26px] text-foreground">产品体验</h2>
            <Link
              href="/products"
              className="text-[12px] text-primary hover:text-brand-hover transition-colors"
            >
              查看全部 →
            </Link>
          </div>

          {experiences.items.length === 0 ? (
            <p
              className="text-[14px] text-muted-foreground font-serif italic"
              data-testid="dashboard-experience-empty"
            >
              还没有产品体验报告，等候首次自动体验或点击上方「体验产品」手动触发。
            </p>
          ) : (
            <div className="space-y-4">
              <div
                className="rounded-2xl bg-card px-6 py-4 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2"
                style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
              >
                <div>
                  <p className="text-[11px] font-medium text-muted-foreground tracking-[0.15em]">
                    累计体验报告
                  </p>
                  <p className="font-serif text-[28px] text-foreground mt-1 leading-none tabular-nums">
                    {experiences.total}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-[11px] font-medium text-muted-foreground tracking-[0.15em]">
                    最近一次
                  </p>
                  <p className="text-[13px] text-foreground font-serif italic mt-1">
                    {formatRelative(experiences.items[0].run_completed_at)}
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                {experiences.items.map((report) => (
                  <Link
                    key={report.id}
                    href={`/products/${report.id}`}
                    className="flex items-center gap-4 rounded-xl bg-card px-4 py-3 transition-all hover:bg-secondary/30"
                    style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
                    data-testid={`dashboard-experience-card-${report.id}`}
                  >
                    <span
                      className="text-[10px] font-medium tracking-wider text-primary px-2 py-0.5 rounded-md shrink-0"
                      style={{
                        background: "rgba(201, 100, 66, 0.08)",
                        boxShadow: "0 0 0 1px rgba(201, 100, 66, 0.2)",
                      }}
                    >
                      {EXPERIENCE_STATUS_LABELS[report.status] ?? report.status}
                    </span>
                    <span className="font-serif text-[15px] text-foreground flex-1 truncate">
                      {report.product_name}
                    </span>
                    <span className="text-[11px] text-muted-foreground font-serif italic shrink-0">
                      {EXPERIENCE_LOGIN_LABELS[report.login_used] ?? report.login_used}
                    </span>
                    {report.overall_ux_score != null && (
                      <ScoreIndicator score={report.overall_ux_score} />
                    )}
                  </Link>
                ))}
              </div>
            </div>
          )}
        </section>
      )}

      {/* Per-source table */}
      {sourceStats && sourceStats.items.length > 0 && (
        <section>
          <div className="flex items-baseline justify-between mb-5">
            <h2 className="font-serif text-[26px] text-foreground">各数据源</h2>
            <p className="text-[12px] text-muted-foreground font-serif italic">
              {sourceStats.total_sources} 个源 · {sourceStats.total_items} 条数据
            </p>
          </div>
          <div
            className="rounded-2xl bg-card overflow-hidden"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            <div className="grid grid-cols-[1fr_auto_auto_auto] gap-x-6 px-6 py-3 text-[11px] font-medium text-muted-foreground tracking-[0.12em] border-b border-border">
              <span>数据源</span>
              <span className="text-right">条数</span>
              <span className="text-right">待处理</span>
              <span className="text-right">上次采集</span>
            </div>
            {sourceStats.items.map((s, idx) => (
              <div
                key={s.source}
                className={`grid grid-cols-[1fr_auto_auto_auto] gap-x-6 px-6 py-3 items-center text-[13px] ${
                  idx % 2 === 0 ? "bg-card" : "bg-secondary/20"
                }`}
              >
                <span className="font-serif text-foreground truncate">{s.source}</span>
                <span className="text-right text-foreground tabular-nums">{s.count}</span>
                <span className="text-right text-muted-foreground tabular-nums">
                  {s.unprocessed}
                </span>
                <span className="text-right text-muted-foreground font-serif italic text-[12px]">
                  {formatRelative(s.last_collected_at)}
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Recent items */}
      <section>
        <div className="flex items-baseline justify-between mb-5">
          <h2 className="font-serif text-[26px] text-foreground">最新数据</h2>
          <Link
            href="/sources"
            className="text-[12px] text-primary hover:text-brand-hover transition-colors"
          >
            查看全部 →
          </Link>
        </div>
        {sourceData?.items?.length ? (
          <div className="space-y-1.5">
            {sourceData.items.map((item) => (
              <div
                key={item.id}
                className="flex items-center gap-4 rounded-xl bg-card px-4 py-3 transition-all hover:bg-secondary/30"
                style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
              >
                <span
                  className="text-[10px] font-medium tracking-wider text-primary px-2 py-0.5 rounded-md shrink-0"
                  style={{
                    background: "rgba(201, 100, 66, 0.08)",
                    boxShadow: "0 0 0 1px rgba(201, 100, 66, 0.2)",
                  }}
                >
                  {item.source}
                </span>
                <a
                  href={item.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="font-serif text-[15px] text-foreground hover:text-primary transition-colors flex-1 truncate"
                >
                  {item.title}
                </a>
                {item.score != null && (
                  <span className="text-[11px] text-muted-foreground tabular-nums shrink-0">
                    {item.score.toFixed(1)}
                  </span>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p
            className="text-[14px] text-muted-foreground font-serif italic"
            data-testid="dashboard-empty-state"
          >
            暂未采集到数据。
          </p>
        )}
      </section>

      {/* Recent ideas */}
      {analysisData?.items?.length ? (
        <section>
          <div className="flex items-baseline justify-between mb-5">
            <h2 className="font-serif text-[26px] text-foreground">近期创意</h2>
            <p className="text-[12px] text-muted-foreground font-serif italic">
              由分析 Agent 精选
            </p>
          </div>
          <div className="space-y-3">
            {analysisData.items.map((result) => (
              <div
                key={result.id}
                className="rounded-2xl bg-card px-6 py-5"
                style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
              >
                <div className="flex justify-between items-start gap-4">
                  <h3 className="font-serif text-[18px] text-foreground leading-snug">
                    {result.idea_title.slice(0, 100)}
                  </h3>
                  <ScoreIndicator score={result.overall_score} />
                </div>
                {result.product_idea && (
                  <p className="text-[14px] text-muted-foreground mt-2 line-clamp-3">
                    {result.product_idea.slice(0, 300)}
                  </p>
                )}
                <p className="text-[11px] text-muted-foreground mt-3 font-serif italic">
                  {new Date(result.created_at).toLocaleDateString("zh-CN")}
                </p>
              </div>
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function HealthBadge({
  label,
  status,
  testId,
}: {
  label: string;
  status: "ok" | "fail";
  testId: string;
}) {
  const ok = status === "ok";
  return (
    <span
      className="inline-flex items-center gap-2 px-3 py-1.5 rounded-md text-[12px] tracking-tight"
      style={{
        color: ok ? "#5b6b43" : "#8a2525",
        background: ok
          ? "rgba(122, 140, 92, 0.12)"
          : "rgba(181, 51, 51, 0.08)",
        boxShadow: `0 0 0 1px ${
          ok ? "rgba(122, 140, 92, 0.35)" : "rgba(181, 51, 51, 0.35)"
        }`,
      }}
      data-testid={testId}
      data-status={status}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: ok ? "#5b6b43" : "#8a2525" }}
      />
      {label} · {ok ? "正常" : "异常"}
    </span>
  );
}
