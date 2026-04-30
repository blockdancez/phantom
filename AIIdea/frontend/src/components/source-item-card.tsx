import Link from "next/link";
import type { SourceItem } from "@/lib/types";
import { TagBadge } from "./tag-badge";
import { ScoreIndicator } from "./score-indicator";

interface SourceItemCardProps {
  item: SourceItem;
}

// Strip basic HTML tags from RSS summaries before we fall back to raw content.
function stripTags(s: string): string {
  return s.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

export function SourceItemCard({ item }: SourceItemCardProps) {
  const hasInsights = Boolean(
    item.summary_zh || item.problem || item.opportunity || item.target_user || item.why_now
  );
  const preview =
    item.summary_zh ||
    (item.content ? stripTags(item.content).slice(0, 240) : "");

  return (
    <div
      className="rounded-xl bg-card px-5 py-4 transition-all hover:bg-secondary/30"
      style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
    >
      <div className="flex justify-between items-start gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-2 flex-wrap">
            <span
              className="text-[10px] font-medium tracking-wider text-primary px-2 py-0.5 rounded-md"
              style={{
                background: "rgba(201, 100, 66, 0.08)",
                boxShadow: "0 0 0 1px rgba(201, 100, 66, 0.2)",
              }}
            >
              {item.source}
            </span>
            <ProcessStatusBadge processed={item.processed} />
            {item.category && (
              <span className="text-[11px] text-muted-foreground font-serif italic">
                {item.category}
              </span>
            )}
          </div>
          <Link
            href={`/sources/${item.id}`}
            className="font-serif text-[17px] text-foreground hover:text-primary transition-colors block leading-snug"
          >
            {item.title}
          </Link>
          {preview && (
            <p className="text-[13.5px] text-muted-foreground mt-1.5 line-clamp-3 leading-relaxed">
              {preview}
            </p>
          )}
          {item.tags && item.tags.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-3">
              {item.tags.map((tag) => (
                <TagBadge key={tag} tag={tag} />
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-col items-end gap-2.5 shrink-0">
          {item.score != null && <ScoreIndicator score={item.score} />}
          <a
            href={item.url}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="查看原网站"
            title="查看原网站"
            className="text-[11px] text-primary hover:text-brand-hover transition-colors inline-flex items-center gap-1 px-2 py-1 rounded-md"
            style={{
              background: "rgba(201, 100, 66, 0.06)",
              boxShadow: "0 0 0 1px rgba(201, 100, 66, 0.2)",
            }}
          >
            原网站
            <span aria-hidden className="text-[10px]">↗</span>
          </a>
        </div>
      </div>

      {hasInsights && (
        <details className="mt-4 group">
          <summary
            className="text-[12px] text-primary cursor-pointer list-none select-none hover:text-brand-hover transition-colors font-serif italic"
          >
            <span className="inline-block transition-transform group-open:rotate-90 mr-1">▸</span>
            展开情报
          </summary>
          <div className="mt-3 space-y-3 text-[13px] leading-relaxed border-t border-border pt-3">
            {item.problem && (
              <InsightRow label="痛点" value={item.problem} />
            )}
            {item.opportunity && (
              <InsightRow label="机会" value={item.opportunity} />
            )}
            {item.target_user && (
              <InsightRow label="目标用户" value={item.target_user} />
            )}
            {item.why_now && (
              <InsightRow label="时机" value={item.why_now} />
            )}
          </div>
        </details>
      )}

      <p className="text-[11px] text-muted-foreground mt-3 font-serif italic">
        {new Date(item.collected_at).toLocaleString("zh-CN")}
      </p>
    </div>
  );
}

function ProcessStatusBadge({ processed }: { processed: boolean }) {
  if (processed) {
    return (
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
    );
  }
  return (
    <span
      className="text-[10px] font-medium tracking-wider px-2 py-0.5 rounded-md text-muted-foreground"
      style={{
        background: "rgba(120, 113, 108, 0.08)",
        boxShadow: "0 0 0 1px rgba(120, 113, 108, 0.2)",
      }}
    >
      待处理
    </span>
  );
}

function InsightRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[64px_1fr] gap-x-4">
      <span className="text-[11px] text-muted-foreground tracking-wider font-medium pt-0.5">
        {label}
      </span>
      <span className="text-foreground font-serif">{value}</span>
    </div>
  );
}
