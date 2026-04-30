import { notFound } from "next/navigation";
import { ApiError, getAnalysisResult } from "@/lib/api";
import { ScoreIndicator } from "@/components/score-indicator";
import { CopyButton } from "@/components/copy-button";
import Link from "next/link";
import type { AnalysisResult } from "@/lib/types";
import { productTypeLabel } from "@/lib/utils";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AnalysisDetailPage({ params }: Props) {
  const { id } = await params;

  let result: AnalysisResult;
  try {
    result = await getAnalysisResult(id);
  } catch (err) {
    // 404 and invalid UUIDs both deserve the "未找到" page per feature-10
    // error matrix; other failures (500/503) bubble into the global error
    // boundary so the user sees a retry banner instead of an empty page.
    if (
      err instanceof ApiError &&
      (err.code === "ANA001" || err.code === "ANA002")
    ) {
      notFound();
    }
    throw err;
  }

  const sections: Array<[string, string | null | undefined]> = [
    ["产品 idea", result.product_idea],
    ["产品面向人群", result.target_audience],
    ["产品使用场景", result.use_case],
    ["现有的痛点", result.pain_points],
    ["主要的功能", result.key_features],
  ];

  return (
    <div
      className="max-w-4xl mx-auto space-y-8"
      data-testid="analysis-detail-page"
    >
      <nav className="text-[12px] text-muted-foreground">
        <Link href="/analysis" className="hover:text-primary transition-colors">
          ← 返回创意 IDEA
        </Link>
      </nav>

      <header className="space-y-4">
        <h1 className="font-serif text-[32px] text-foreground leading-tight">
          {result.idea_title}
        </h1>
        <div className="flex items-center gap-3 flex-wrap">
          <ScoreIndicator score={result.overall_score} />
          {result.product_type && (
            <span
              className="text-[11px] font-medium tracking-wider px-2.5 py-1 rounded-md text-primary"
              style={{
                background: "rgba(201, 100, 66, 0.08)",
                boxShadow: "0 0 0 1px rgba(201, 100, 66, 0.3)",
              }}
              data-testid="analysis-detail-product-type"
            >
              {productTypeLabel(result.product_type)}
            </span>
          )}
          {result.project_name && (
            <span
              className="text-[12px] font-mono text-muted-foreground px-2.5 py-1 rounded-md bg-secondary/40"
              data-testid="analysis-detail-project-name"
              title="项目英文短名 (project_name)"
            >
              {result.project_name}
            </span>
          )}
          {result.aijuicer_workflow_id && (
            <span
              className="text-[11px] font-medium tracking-wider px-2.5 py-1 rounded-md"
              style={{
                color: "#5b6b43",
                background: "rgba(122, 140, 92, 0.12)",
                boxShadow: "0 0 0 1px rgba(122, 140, 92, 0.35)",
              }}
              data-testid="analysis-detail-aijuicer"
              title={`AIJuicer workflow: ${result.aijuicer_workflow_id}`}
            >
              已入流 AIJuicer
            </span>
          )}
          <span className="text-[12px] text-muted-foreground font-serif italic">
            生成于 {new Date(result.created_at).toLocaleString("zh-CN")}
          </span>
        </div>
      </header>

      {(result.source_item_id || result.source_quote) && (
        <section>
          <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
            数据引用
          </h2>
          <div
            className="rounded-2xl bg-card px-6 py-5 space-y-3"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            {result.source_item_id && result.source_item_title && (
              <Link
                href={`/sources/${result.source_item_id}`}
                className="block font-serif text-[16px] text-foreground hover:text-primary transition-colors leading-snug"
              >
                {result.source_item_title}
                <span className="text-[12px] text-muted-foreground ml-2">→ 查看数据详情</span>
              </Link>
            )}
            {result.source_quote && (
              <blockquote
                className="border-l-2 pl-5 py-1 italic text-[14px] text-muted-foreground leading-relaxed font-serif"
                style={{ borderLeftColor: "var(--color-brand)" }}
              >
                {result.source_quote}
              </blockquote>
            )}
          </div>
        </section>
      )}

      {result.reasoning && (
        <section>
          <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
            依据
          </h2>
          <p
            className="rounded-2xl bg-card px-6 py-5 text-[14px] text-foreground leading-[1.85] font-serif whitespace-pre-wrap"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            {result.reasoning}
          </p>
        </section>
      )}

      {result.user_story && (
        <section>
          <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
            用户故事
          </h2>
          <p
            className="rounded-2xl bg-card px-6 py-5 text-[15px] text-foreground leading-relaxed font-serif"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            {result.user_story}
          </p>
        </section>
      )}

      <div className="space-y-5">
        {sections.map(([label, value]) =>
          value ? (
            <section key={label}>
              <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
                {label}
              </h2>
              <div
                className="rounded-2xl bg-card px-6 py-5"
                style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
              >
                <p className="text-[14px] text-foreground leading-relaxed whitespace-pre-wrap font-serif">
                  {value}
                </p>
              </div>
            </section>
          ) : null,
        )}
      </div>

      {result.agent_trace === null ? (
        <section data-testid="analysis-detail-trace-missing">
          <p className="text-[12px] text-muted-foreground font-serif italic">
            此分析无推理轨迹。
          </p>
        </section>
      ) : Object.keys(result.agent_trace).length > 0 ? (
        (() => {
          let rawMarkdown: string;
          let corrupt = false;
          try {
            rawMarkdown =
              typeof result.agent_trace!.raw_report === "string"
                ? (result.agent_trace!.raw_report as string)
                : JSON.stringify(result.agent_trace, null, 2);
          } catch {
            rawMarkdown = "";
            corrupt = true;
          }
          if (corrupt) {
            return (
              <section
                data-testid="analysis-detail-trace-corrupt"
                className="rounded-2xl bg-card px-6 py-5"
                style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
              >
                <p className="text-[13px] text-destructive font-serif italic">
                  轨迹数据损坏，无法解析。
                </p>
              </section>
            );
          }
          return (
            <section data-testid="analysis-detail-trace">
              <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
                Agent 原始报告
              </h2>
              <details
                className="rounded-2xl bg-card px-6 py-4"
                style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
              >
                <summary className="flex items-center justify-between gap-3 text-[12px] text-primary cursor-pointer list-none select-none font-serif italic hover:text-brand-hover">
                  <span>
                    <span className="mr-1">▸</span>
                    展开原始 Markdown
                  </span>
                  <CopyButton
                    text={rawMarkdown}
                    data-testid="analysis-detail-copy-trace"
                  />
                </summary>
                <pre className="mt-4 text-[12px] text-muted-foreground overflow-x-auto leading-relaxed whitespace-pre-wrap">
                  {rawMarkdown}
                </pre>
              </details>
            </section>
          );
        })()
      ) : null}
    </div>
  );
}
