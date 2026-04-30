"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

interface Props {
  initialMinScore: string;
  initialSort: string;
  initialOrder: string;
}

const MIN_SCORE_OPTIONS = [
  { value: "", label: "不限" },
  { value: "3", label: "≥ 3" },
  { value: "5", label: "≥ 5" },
  { value: "6", label: "≥ 6" },
  { value: "7", label: "≥ 7" },
  { value: "8", label: "≥ 8" },
  { value: "9", label: "≥ 9" },
];

export function AnalysisFilterBar({ initialMinScore, initialSort, initialOrder }: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();
  const [minScore, setMinScore] = useState(initialMinScore);
  const [sort, setSort] = useState(initialSort);
  const [order, setOrder] = useState(initialOrder);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setMinScore(initialMinScore);
    setSort(initialSort);
    setOrder(initialOrder);
  }, [initialMinScore, initialSort, initialOrder]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function apply(next: { min_score?: string; sort?: string; order?: string }) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", "1");

    const setOrDelete = (key: string, value: string) => {
      if (value) params.set(key, value);
      else params.delete(key);
    };
    setOrDelete("min_score", next.min_score ?? minScore);
    setOrDelete("sort", next.sort ?? sort);
    setOrDelete("order", next.order ?? order);

    startTransition(() => {
      router.push(`/analysis?${params.toString()}`);
    });
  }

  return (
    <div
      className="rounded-2xl bg-card px-5 py-4 flex flex-wrap items-center gap-5"
      style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
      data-testid="analysis-filter-bar"
    >
      <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
        <span className="tracking-wider">最低分</span>
        <select
          value={minScore}
          onChange={(e) => {
            const next = e.target.value;
            setMinScore(next);
            apply({ min_score: next });
          }}
          data-testid="analysis-filter-min-score"
          aria-label="按最低 overall_score 筛选"
          className="bg-secondary/60 text-foreground text-[12px] px-2.5 py-1 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40"
          style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
        >
          {MIN_SCORE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
        <span className="tracking-wider">排序字段</span>
        <select
          value={sort}
          onChange={(e) => {
            const next = e.target.value;
            setSort(next);
            apply({ sort: next });
          }}
          data-testid="analysis-filter-sort"
          aria-label="按创建时间或评分排序"
          className="bg-secondary/60 text-foreground text-[12px] px-2.5 py-1 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40"
          style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
        >
          <option value="created_at">创建时间</option>
          <option value="score">评分</option>
        </select>
      </label>

      <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
        <span className="tracking-wider">方向</span>
        <select
          value={order}
          onChange={(e) => {
            const next = e.target.value;
            setOrder(next);
            apply({ order: next });
          }}
          data-testid="analysis-filter-order"
          aria-label="升序或降序"
          className="bg-secondary/60 text-foreground text-[12px] px-2.5 py-1 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40"
          style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
        >
          <option value="desc">降序</option>
          <option value="asc">升序</option>
        </select>
      </label>
    </div>
  );
}
