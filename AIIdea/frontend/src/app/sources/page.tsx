import { getSourceItems, getSourceStats } from "@/lib/api";
import { SourceItemCard } from "@/components/source-item-card";
import { Pagination } from "@/components/pagination";
import { SourcesFilterBar } from "@/components/sources-filter-bar";
import type { SourceItemList, SourceStatsList } from "@/lib/types";
import type { SourceItemsQuery } from "@/lib/api";

interface Props {
  searchParams: Promise<{
    page?: string;
    per_page?: string;
    source?: string;
    category?: string;
    collected_since?: string;
    collected_until?: string;
    q?: string;
    sort?: string;
    order?: string;
  }>;
}

// Plan's sources-list spec wants a category dropdown — we fetch an extra
// page of items to surface category values actually present in the DB so
// the dropdown stays grounded in real data rather than a hard-coded list.
const CATEGORY_SAMPLE_SIZE = 200;

export default async function SourcesPage({ searchParams }: Props) {
  const params = await searchParams;
  const page = Number(params.page) || 1;
  const pageSize = Number(params.per_page) || 20;

  // The plan uses date inputs (YYYY-MM-DD). The backend accepts ISO-8601, so
  // we convert the "until" value to end-of-day UTC to make the upper bound
  // inclusive of the whole date the user picked.
  const collectedSinceRaw = params.collected_since ?? "";
  const collectedUntilRaw = params.collected_until ?? "";

  const query: SourceItemsQuery = {
    page,
    per_page: pageSize,
    source: params.source,
    category: params.category,
    q: params.q,
    sort: (params.sort as "collected_at" | "score" | "title") || "collected_at",
    order: (params.order as "asc" | "desc") || "desc",
    collected_since: collectedSinceRaw || undefined,
    collected_until: collectedUntilRaw
      ? `${collectedUntilRaw}T23:59:59Z`
      : undefined,
  };

  let data: SourceItemList | null = null;
  let stats: SourceStatsList | null = null;
  let categorySample: SourceItemList | null = null;
  let error: string | null = null;

  try {
    [data, stats, categorySample] = await Promise.all([
      getSourceItems(query),
      getSourceStats(),
      getSourceItems({ page: 1, per_page: CATEGORY_SAMPLE_SIZE }),
    ]);
  } catch {
    error = "加载数据失败。";
  }

  const categories = Array.from(
    new Set(
      (categorySample?.items ?? [])
        .map((it) => it.category)
        .filter((c): c is string => typeof c === "string" && c.length > 0),
    ),
  ).sort();

  const hasFilter = Boolean(
    params.q ||
      params.source ||
      params.category ||
      collectedSinceRaw ||
      collectedUntilRaw,
  );

  return (
    <div
      className="max-w-6xl mx-auto space-y-6"
      data-testid="sources-list-page"
    >
      <header>
        <p className="text-[11px] font-medium tracking-[0.2em] text-muted-foreground">
          数据档案
        </p>
        <h1 className="font-serif text-[40px] text-foreground mt-2 leading-[1.15]">
          数据
        </h1>
        <p className="text-[15px] text-muted-foreground mt-3 max-w-2xl">
          从 Hacker News、arxiv、Reddit、产品发布站等渠道源源不断汇入的原始信号。按来源、分类或日期范围筛选浏览。
        </p>
      </header>

      {stats && stats.items.length > 0 && (
        <SourcesFilterBar
          sources={stats.items}
          categories={categories}
          initialQuery={params.q ?? ""}
          initialSource={params.source ?? ""}
          initialCategory={params.category ?? ""}
          initialCollectedSince={collectedSinceRaw}
          initialCollectedUntil={collectedUntilRaw}
          initialSort={params.sort ?? "collected_at"}
          initialOrder={params.order ?? "desc"}
        />
      )}

      {error && (
        <div
          className="rounded-xl px-5 py-4 text-[13.5px] text-destructive"
          data-testid="sources-list-error"
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
            {hasFilter
              ? `筛选得到 ${data.total} 条`
              : `共归档 ${data.total} 条`}
          </p>
          <div
            className="space-y-3"
            data-testid="sources-list-container"
          >
            {data.items.map((item) => (
              <SourceItemCard key={item.id} item={item} />
            ))}
          </div>
          <Pagination total={data.total} page={page} pageSize={pageSize} basePath="/sources" />
        </>
      ) : !error ? (
        <p
          className="text-[14px] text-muted-foreground font-serif italic"
          data-testid="sources-list-empty"
        >
          {hasFilter ? "没有匹配的数据，试试调整筛选条件。" : "暂未采集到数据。"}
        </p>
      ) : null}
    </div>
  );
}
