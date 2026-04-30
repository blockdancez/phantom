import Link from "next/link";
import type { AnalysisResult } from "@/lib/types";
import { productTypeLabel } from "@/lib/utils";
import { ScoreIndicator } from "./score-indicator";

interface AnalysisCardProps {
  result: AnalysisResult;
}

export function AnalysisCard({ result }: AnalysisCardProps) {
  // user_story is the main hook when present (newer rows); fall back to
  // product_idea for legacy rows that were parsed before the lineage change.
  const preview = result.user_story ?? result.product_idea ?? "";
  return (
    <Link href={`/analysis/${result.id}`} className="block group">
      <div
        className="rounded-2xl bg-card px-6 py-5 transition-all group-hover:bg-secondary/30"
        style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
      >
        <div className="flex justify-between items-start gap-5">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-serif text-[20px] text-foreground group-hover:text-primary transition-colors leading-snug">
                {result.idea_title}
              </h3>
              {result.product_type && (
                <span
                  className="text-[10px] font-medium tracking-wider px-2 py-0.5 rounded-md text-primary shrink-0"
                  style={{
                    background: "rgba(201, 100, 66, 0.08)",
                    boxShadow: "0 0 0 1px rgba(201, 100, 66, 0.25)",
                  }}
                  data-testid={`analysis-card-product-type-${result.id}`}
                >
                  {productTypeLabel(result.product_type)}
                </span>
              )}
              {result.aijuicer_workflow_id && (
                <span
                  className="text-[10px] font-medium tracking-wider px-2 py-0.5 rounded-md shrink-0"
                  style={{
                    color: "#5b6b43",
                    background: "rgba(122, 140, 92, 0.12)",
                    boxShadow: "0 0 0 1px rgba(122, 140, 92, 0.35)",
                  }}
                  data-testid={`analysis-card-aijuicer-${result.id}`}
                  title={`AIJuicer workflow: ${result.aijuicer_workflow_id}`}
                >
                  已入流
                </span>
              )}
            </div>
            {result.project_name && (
              <p
                className="text-[11px] font-mono text-muted-foreground mt-1.5"
                data-testid={`analysis-card-project-name-${result.id}`}
              >
                {result.project_name}
              </p>
            )}
            {preview && (
              <p className="text-[14px] text-muted-foreground mt-2.5 line-clamp-3 leading-relaxed">
                {preview}
              </p>
            )}
          </div>
          <ScoreIndicator score={result.overall_score} />
        </div>
        <div className="flex items-center gap-3 mt-4 text-[12px] text-muted-foreground">
          <span className="font-serif italic">
            {new Date(result.created_at).toLocaleString("zh-CN")}
          </span>
          {result.target_audience && (
            <>
              <span className="text-border">·</span>
              <span className="font-serif italic truncate max-w-[240px]">
                面向 {result.target_audience.slice(0, 30)}
              </span>
            </>
          )}
        </div>
      </div>
    </Link>
  );
}
