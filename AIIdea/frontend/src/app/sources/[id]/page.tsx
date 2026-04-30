import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, getSourceItem } from "@/lib/api";
import { CopyButton } from "@/components/copy-button";
import { ScoreIndicator } from "@/components/score-indicator";
import { TagBadge } from "@/components/tag-badge";
import type { SourceItem } from "@/lib/types";

interface Props {
  params: Promise<{ id: string }>;
}

function stripTags(s: string): string {
  return s.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

export default async function SourceItemDetailPage({ params }: Props) {
  const { id } = await params;

  let item: SourceItem;
  try {
    item = await getSourceItem(id);
  } catch (err) {
    // Only map real 404 / invalid-UUID responses to the Chinese not-found
    // page. Transient 500 / 503 should surface as server errors so the user
    // can retry instead of seeing an empty "条目不存在" state.
    if (
      err instanceof ApiError &&
      (err.code === "SRC001" || err.code === "SRC002")
    ) {
      notFound();
    }
    throw err;
  }

  const insights: Array<[string, string | null]> = [
    ["痛点", item.problem],
    ["机会", item.opportunity],
    ["目标用户", item.target_user],
    ["时机", item.why_now],
  ];
  const hasInsights = insights.some(([, v]) => Boolean(v));
  const cleanContent = item.content ? stripTags(item.content) : "";

  return (
    <div
      className="max-w-4xl mx-auto space-y-8"
      data-testid="source-detail-page"
    >
      <nav className="text-[12px] text-muted-foreground">
        <Link href="/sources" className="hover:text-primary transition-colors">
          ← 返回数据
        </Link>
      </nav>

      <header className="space-y-4">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="text-[10px] font-medium tracking-wider text-primary px-2 py-0.5 rounded-md"
            style={{
              background: "rgba(201, 100, 66, 0.08)",
              boxShadow: "0 0 0 1px rgba(201, 100, 66, 0.2)",
            }}
          >
            {item.source}
          </span>
          {item.processed ? (
            <span
              className="text-[10px] font-medium tracking-wider px-2 py-0.5 rounded-md"
              style={{
                color: "#5b6b43",
                background: "rgba(122, 140, 92, 0.12)",
                boxShadow: "0 0 0 1px rgba(122, 140, 92, 0.3)",
              }}
            >
              已处理
            </span>
          ) : (
            <span
              className="text-[10px] font-medium tracking-wider px-2 py-0.5 rounded-md text-muted-foreground"
              style={{
                background: "rgba(120, 113, 108, 0.08)",
                boxShadow: "0 0 0 1px rgba(120, 113, 108, 0.2)",
              }}
            >
              待处理
            </span>
          )}
          {item.category && (
            <span className="text-[12px] text-muted-foreground font-serif italic">
              {item.category}
            </span>
          )}
        </div>

        <h1 className="font-serif text-[32px] text-foreground leading-tight">
          {item.title}
        </h1>

        <div className="flex items-center gap-4 flex-wrap">
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            data-testid="source-detail-open-origin"
            aria-label="在新窗口打开原始网页"
            className="text-[13px] text-primary hover:text-brand-hover transition-colors inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md"
            style={{
              background: "rgba(201, 100, 66, 0.08)",
              boxShadow: "0 0 0 1px rgba(201, 100, 66, 0.25)",
            }}
          >
            查看原网站
            <span aria-hidden>↗</span>
          </a>
          <CopyButton
            text={item.url}
            data-testid="source-detail-copy-url"
            aria-label="复制原始网页 URL"
          />
          {item.score != null && <ScoreIndicator score={item.score} />}
        </div>

        {item.tags && item.tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {item.tags.map((t) => (
              <TagBadge key={t} tag={t} />
            ))}
          </div>
        )}
      </header>

      {item.summary_zh && (
        <section>
          <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
            摘要
          </h2>
          <p className="font-serif text-[16px] text-foreground leading-relaxed">
            {item.summary_zh}
          </p>
        </section>
      )}

      {hasInsights && (
        <section>
          <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
            情报
          </h2>
          <div
            className="rounded-2xl bg-card px-6 py-5 space-y-4"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            {insights.map(([label, value]) =>
              value ? (
                <div key={label} className="grid grid-cols-[72px_1fr] gap-x-4">
                  <span className="text-[11px] text-muted-foreground tracking-wider font-medium pt-0.5">
                    {label}
                  </span>
                  <span className="text-[14px] text-foreground font-serif leading-relaxed">
                    {value}
                  </span>
                </div>
              ) : null,
            )}
          </div>
        </section>
      )}

      {cleanContent && (
        <section>
          <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
            原文内容
          </h2>
          <div
            className="rounded-2xl bg-card px-6 py-5"
            style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
          >
            <p className="text-[14px] text-foreground leading-relaxed whitespace-pre-wrap font-serif">
              {cleanContent}
            </p>
          </div>
        </section>
      )}

      <section>
        <h2 className="text-[11px] font-medium tracking-[0.15em] text-muted-foreground mb-3">
          原数据
        </h2>
        <details
          className="rounded-2xl bg-card px-6 py-4"
          style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
        >
          <summary className="text-[12px] text-primary cursor-pointer list-none select-none font-serif italic hover:text-brand-hover">
            <span className="mr-1">▸</span>
            展开 raw_data (JSON)
          </summary>
          <pre className="mt-4 text-[12px] text-muted-foreground overflow-x-auto leading-relaxed">
            {JSON.stringify(item.raw_data, null, 2)}
          </pre>
        </details>
      </section>

      {item.analysis_result_id && (
        <section data-testid="source-detail-analysis-link-section">
          <Link
            href={`/analysis/${item.analysis_result_id}`}
            data-testid="source-detail-view-analysis"
            aria-label="查看基于本数据条目生成的创意 IDEA"
            className="inline-flex items-center gap-2 text-[13px] text-primary hover:text-brand-hover transition-colors px-4 py-2 rounded-md"
            style={{
              background: "rgba(201, 100, 66, 0.08)",
              boxShadow: "0 0 0 1px rgba(201, 100, 66, 0.3)",
            }}
          >
            查看分析
            <span aria-hidden>→</span>
          </Link>
        </section>
      )}

      <footer className="text-[12px] text-muted-foreground font-serif italic space-y-1 pt-4 border-t border-border">
        <p>ID：{item.id}</p>
        <p>采集时间：{new Date(item.collected_at).toLocaleString("zh-CN")}</p>
        <p>入库时间：{new Date(item.created_at).toLocaleString("zh-CN")}</p>
      </footer>
    </div>
  );
}
