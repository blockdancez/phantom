"use client";

import { useRouter, useSearchParams } from "next/navigation";

interface PaginationProps {
  total: number;
  page: number;
  pageSize: number;
  basePath: string;
}

export function Pagination({ total, page, pageSize, basePath }: PaginationProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const totalPages = Math.ceil(total / pageSize);

  if (totalPages <= 1) return null;

  const goToPage = (p: number) => {
    // Preserve all current query params (filters, sort, etc.) and only override page.
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", String(p));
    params.set("per_page", String(pageSize));
    router.push(`${basePath}?${params.toString()}`);
  };

  return (
    <div className="flex items-center justify-center gap-4 mt-10">
      <button
        onClick={() => goToPage(page - 1)}
        disabled={page <= 1}
        className="px-4 py-2 text-[13px] font-medium tracking-tight rounded-lg bg-secondary/50 text-secondary-foreground transition-all disabled:opacity-30 disabled:cursor-not-allowed hover:bg-secondary"
        style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
      >
        ← 上一页
      </button>
      <span className="text-[13px] text-muted-foreground tabular-nums font-serif italic">
        第 {page} / {totalPages} 页
      </span>
      <button
        onClick={() => goToPage(page + 1)}
        disabled={page >= totalPages}
        className="px-4 py-2 text-[13px] font-medium tracking-tight rounded-lg bg-secondary/50 text-secondary-foreground transition-all disabled:opacity-30 disabled:cursor-not-allowed hover:bg-secondary"
        style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
      >
        下一页 →
      </button>
    </div>
  );
}
