import { getAnalysisResults } from "@/lib/api";
import { AnalysisCard } from "@/components/analysis-card";
import { AnalysisFilterBar } from "@/components/analysis-filter-bar";
import { Pagination } from "@/components/pagination";

interface Props {
  searchParams: Promise<{
    page?: string;
    per_page?: string;
    min_score?: string;
    sort?: string;
    order?: string;
  }>;
}

export default async function AnalysisPage({ searchParams }: Props) {
  const params = await searchParams;
  const page = Number(params.page) || 1;
  const pageSize = Number(params.per_page) || 20;
  const minScoreRaw = params.min_score ?? "";
  const minScoreNumber = minScoreRaw ? Number(minScoreRaw) : undefined;
  const sortParam = params.sort === "score" ? "score" : "created_at";
  const orderParam = params.order === "asc" ? "asc" : "desc";

  let data = null;
  let error = null;

  try {
    data = await getAnalysisResults({
      page,
      per_page: pageSize,
      min_score: minScoreNumber,
      sort: sortParam,
      order: orderParam,
    });
  } catch {
    error = "加载分析结果失败。";
  }

  return (
    <div
      className="max-w-6xl mx-auto space-y-8"
      data-testid="analysis-list-page"
    >
      <header>
        <p className="text-[11px] font-medium tracking-[0.2em] text-muted-foreground">
          Agent 笔记本
        </p>
        <h1 className="font-serif text-[40px] text-foreground mt-2 leading-[1.15]">
          创意 IDEA
        </h1>
        <p className="text-[15px] text-muted-foreground mt-3 max-w-2xl">
          分析 Agent 阅读全部采集信号后归纳出的产品创意与趋势，已按可行性打分，便于快速浏览。
        </p>
      </header>

      <AnalysisFilterBar
        initialMinScore={minScoreRaw}
        initialSort={sortParam}
        initialOrder={orderParam}
      />

      {error && (
        <div
          className="rounded-xl px-5 py-4 text-[13.5px] text-destructive"
          data-testid="analysis-list-error"
          style={{
            background: "rgba(181, 51, 51, 0.06)",
            boxShadow: "0 0 0 1px rgba(181, 51, 51, 0.25)",
          }}
        >
          {error}
        </div>
      )}

      {data?.items?.length ? (
        <>
          <p className="text-[12px] text-muted-foreground tabular-nums font-serif italic">
            已生成 {data.total} 份报告
          </p>
          <div
            className="space-y-4"
            data-testid="analysis-list-container"
          >
            {data.items.map((result) => (
              <AnalysisCard key={result.id} result={result} />
            ))}
          </div>
          <Pagination total={data.total} page={page} pageSize={pageSize} basePath="/analysis" />
        </>
      ) : !error ? (
        <p
          className="text-[14px] text-muted-foreground font-serif italic"
          data-testid="analysis-list-empty"
        >
          {minScoreNumber != null && minScoreNumber > 0
            ? `暂无 overall_score ≥ ${minScoreNumber} 的分析结果。`
            : "暂无分析结果，Agent 会按计划周期运行。"}
        </p>
      ) : null}
    </div>
  );
}
