"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useTransition } from "react";
import type { SourceStat } from "@/lib/types";

interface Props {
  sources: SourceStat[];
  categories: string[];
  initialQuery: string;
  initialSource: string;
  initialCategory: string;
  initialCollectedSince: string;
  initialCollectedUntil: string;
  initialSort: string;
  initialOrder: string;
}

const SORT_OPTIONS = [
  { value: "collected_at", label: "采集时间" },
  { value: "score", label: "评分" },
  { value: "title", label: "标题" },
];

export function SourcesFilterBar({
  sources,
  categories,
  initialQuery,
  initialSource,
  initialCategory,
  initialCollectedSince,
  initialCollectedUntil,
  initialSort,
  initialOrder,
}: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();

  const [q, setQ] = useState(initialQuery);
  const [source, setSource] = useState(initialSource);
  const [category, setCategory] = useState(initialCategory);
  const [collectedSince, setCollectedSince] = useState(initialCollectedSince);
  const [collectedUntil, setCollectedUntil] = useState(initialCollectedUntil);
  const [sort, setSort] = useState(initialSort);
  const [order, setOrder] = useState(initialOrder);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setQ(initialQuery);
    setSource(initialSource);
    setCategory(initialCategory);
    setCollectedSince(initialCollectedSince);
    setCollectedUntil(initialCollectedUntil);
    setSort(initialSort);
    setOrder(initialOrder);
  }, [
    initialQuery,
    initialSource,
    initialCategory,
    initialCollectedSince,
    initialCollectedUntil,
    initialSort,
    initialOrder,
  ]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function apply(
    overrides: Partial<{
      q: string;
      source: string;
      category: string;
      collected_since: string;
      collected_until: string;
      sort: string;
      order: string;
    }> = {},
  ) {
    const next = new URLSearchParams(searchParams.toString());
    next.set("page", "1");

    const setOrDelete = (key: string, value: string) => {
      if (value) next.set(key, value);
      else next.delete(key);
    };

    setOrDelete("q", overrides.q ?? q);
    setOrDelete("source", overrides.source ?? source);
    setOrDelete("category", overrides.category ?? category);
    setOrDelete("collected_since", overrides.collected_since ?? collectedSince);
    setOrDelete("collected_until", overrides.collected_until ?? collectedUntil);
    setOrDelete("sort", overrides.sort ?? sort);
    setOrDelete("order", overrides.order ?? order);

    startTransition(() => {
      router.push(`/sources?${next.toString()}`);
    });
  }

  function reset() {
    setQ("");
    setSource("");
    setCategory("");
    setCollectedSince("");
    setCollectedUntil("");
    setSort("collected_at");
    setOrder("desc");
    startTransition(() => {
      router.push("/sources");
    });
  }

  const hasActiveFilter =
    Boolean(q || source || category || collectedSince || collectedUntil) ||
    sort !== "collected_at" ||
    order !== "desc";

  return (
    <div
      className="rounded-2xl bg-card px-5 py-4 space-y-3"
      style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
      data-testid="sources-filter-bar"
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          apply();
        }}
        className="flex items-center gap-2"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-muted-foreground shrink-0"
          aria-hidden
        >
          <circle cx="11" cy="11" r="8" />
          <path d="m21 21-4.3-4.3" />
        </svg>
        <input
          type="text"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索标题或内容…"
          data-testid="sources-filter-search"
          aria-label="按关键词搜索标题或内容"
          className="flex-1 bg-transparent outline-none text-[14px] text-foreground placeholder:text-muted-foreground/60 font-serif"
        />
        {q && (
          <button
            type="button"
            onClick={() => {
              setQ("");
              apply({ q: "" });
            }}
            data-testid="sources-filter-search-clear"
            aria-label="清除搜索关键词"
            className="text-[12px] text-muted-foreground hover:text-primary transition-colors"
          >
            清除
          </button>
        )}
      </form>

      <div className="h-px bg-border" />

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <span className="tracking-wider">来源</span>
          <select
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              apply({ source: e.target.value });
            }}
            data-testid="sources-filter-source"
            aria-label="按数据来源筛选"
            className="bg-secondary/60 text-foreground text-[12px] px-2.5 py-1 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40 max-w-[200px]"
            style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
          >
            <option value="">全部</option>
            {sources.map((s) => (
              <option key={s.source} value={s.source}>
                {s.source} ({s.count})
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <span className="tracking-wider">分类</span>
          <select
            value={category}
            onChange={(e) => {
              setCategory(e.target.value);
              apply({ category: e.target.value });
            }}
            data-testid="sources-filter-category"
            aria-label="按内容分类筛选"
            className="bg-secondary/60 text-foreground text-[12px] px-2.5 py-1 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40 max-w-[200px]"
            style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
          >
            <option value="">全部</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <span className="tracking-wider">采集自</span>
          <input
            type="date"
            value={collectedSince}
            onChange={(e) => {
              setCollectedSince(e.target.value);
              apply({ collected_since: e.target.value });
            }}
            data-testid="sources-filter-date-from"
            aria-label="采集时间下限（起始日期）"
            className="bg-secondary/60 text-foreground text-[12px] px-2 py-1 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40"
            style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
          />
        </label>

        <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <span className="tracking-wider">至</span>
          <input
            type="date"
            value={collectedUntil}
            onChange={(e) => {
              setCollectedUntil(e.target.value);
              apply({ collected_until: e.target.value });
            }}
            data-testid="sources-filter-date-to"
            aria-label="采集时间上限（结束日期）"
            className="bg-secondary/60 text-foreground text-[12px] px-2 py-1 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40"
            style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
          />
        </label>

        <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <span className="tracking-wider">排序</span>
          <select
            value={sort}
            onChange={(e) => {
              setSort(e.target.value);
              apply({ sort: e.target.value });
            }}
            data-testid="sources-filter-sort"
            aria-label="排序字段"
            className="bg-secondary/60 text-foreground text-[12px] px-2.5 py-1 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40"
            style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
          >
            {SORT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => {
              const next = order === "desc" ? "asc" : "desc";
              setOrder(next);
              apply({ order: next });
            }}
            data-testid="sources-filter-order"
            aria-label={order === "desc" ? "切换为升序" : "切换为降序"}
            title={order === "desc" ? "降序" : "升序"}
            className="text-[13px] text-foreground hover:text-primary transition-colors px-1"
          >
            {order === "desc" ? "↓" : "↑"}
          </button>
        </label>

        {hasActiveFilter && (
          <button
            type="button"
            onClick={reset}
            data-testid="sources-filter-reset"
            aria-label="重置所有筛选"
            className="ml-auto text-[12px] text-muted-foreground hover:text-primary transition-colors font-serif italic"
          >
            重置筛选
          </button>
        )}
      </div>
    </div>
  );
}
