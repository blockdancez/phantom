import { listProductExperienceReports } from "@/lib/api";
import { ProductExperienceCard } from "@/components/product-experience-card";
import { ProductExperienceFilterBar } from "@/components/product-experience-filter-bar";
import { ManualExperienceForm } from "@/components/manual-experience-form";
import { Pagination } from "@/components/pagination";

export const dynamic = "force-dynamic";

interface Props {
  searchParams: Promise<{
    page?: string;
    per_page?: string;
    product_slug?: string;
    q?: string;
    status?: string;
    min_score?: string;
    sort?: string;
    order?: string;
  }>;
}

export default async function ProductsPage({ searchParams }: Props) {
  const sp = await searchParams;
  const page = Number(sp.page) || 1;
  const pageSize = Number(sp.per_page) || 20;
  const qRaw = sp.q ?? "";
  const statusRaw = ["completed", "partial", "failed"].includes(sp.status ?? "")
    ? (sp.status as "completed" | "partial" | "failed")
    : undefined;
  const minScoreRaw = sp.min_score ?? "";
  const minScoreNumber = minScoreRaw ? Number(minScoreRaw) : undefined;
  const sortParam = ["started_at", "completed_at", "score"].includes(sp.sort ?? "")
    ? (sp.sort as "started_at" | "completed_at" | "score")
    : "started_at";
  const orderParam = sp.order === "asc" ? "asc" : "desc";

  let data = null;
  let error = null;

  try {
    data = await listProductExperienceReports({
      page,
      per_page: pageSize,
      product_slug: sp.product_slug,
      q: qRaw || undefined,
      status: statusRaw,
      min_score: minScoreNumber,
      sort: sortParam,
      order: orderParam,
    });
  } catch {
    error = "加载产品体验报告失败。";
  }

  return (
    <div
      className="max-w-6xl mx-auto space-y-8"
      data-testid="products-list-page"
    >
      <header>
        <p className="text-[11px] font-medium tracking-[0.2em] text-muted-foreground">
          Agent 实战
        </p>
        <h1 className="font-serif text-[40px] text-foreground mt-2 leading-[1.15]">
          产品体验
        </h1>
        <p className="text-[15px] text-muted-foreground mt-3 max-w-2xl">
          Agent 真实打开浏览器逐个产品深度体验，输出截图、功能盘点与综合分，便于侧写竞品和发现工艺细节。
        </p>
      </header>

      <ManualExperienceForm />

      <ProductExperienceFilterBar
        initialQ={qRaw}
        initialStatus={statusRaw ?? ""}
        initialMinScore={minScoreRaw}
        initialSort={sortParam}
        initialOrder={orderParam}
      />

      {error && (
        <div
          className="rounded-xl px-5 py-4 text-[13.5px] text-destructive"
          data-testid="products-list-error"
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
            共 {data.total} 份报告
          </p>
          <div className="space-y-4" data-testid="products-list-container">
            {data.items.map((item) => (
              <ProductExperienceCard key={item.id} item={item} />
            ))}
          </div>
          <Pagination total={data.total} page={page} pageSize={pageSize} basePath="/products" />
        </>
      ) : !error ? (
        <p
          className="text-[14px] text-muted-foreground font-serif italic"
          data-testid="products-list-empty"
        >
          {qRaw || statusRaw || minScoreNumber
            ? "没有匹配当前筛选的产品体验报告。"
            : "还没有产品体验报告。后台 cron 会按计划周期跑，或在仪表盘点击「体验产品」手动触发。"}
        </p>
      ) : null}
    </div>
  );
}
