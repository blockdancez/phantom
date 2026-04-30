"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

interface Props {
  initialQ: string;
  initialStatus: string;
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

const STATUS_OPTIONS = [
  { value: "", label: "全部" },
  { value: "completed", label: "完成" },
  { value: "partial", label: "部分完成" },
  { value: "failed", label: "失败" },
];

export function ProductExperienceFilterBar({
  initialQ,
  initialStatus,
  initialMinScore,
  initialSort,
  initialOrder,
}: Props) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [, startTransition] = useTransition();
  const [q, setQ] = useState(initialQ);
  const [status, setStatus] = useState(initialStatus);
  const [minScore, setMinScore] = useState(initialMinScore);
  const [sort, setSort] = useState(initialSort);
  const [order, setOrder] = useState(initialOrder);

  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setQ(initialQ);
    setStatus(initialStatus);
    setMinScore(initialMinScore);
    setSort(initialSort);
    setOrder(initialOrder);
  }, [initialQ, initialStatus, initialMinScore, initialSort, initialOrder]);
  /* eslint-enable react-hooks/set-state-in-effect */

  function apply(next: Partial<{
    q: string;
    status: string;
    min_score: string;
    sort: string;
    order: string;
  }>) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", "1");
    const setOrDelete = (key: string, value: string) => {
      if (value) params.set(key, value);
      else params.delete(key);
    };
    setOrDelete("q", next.q ?? q);
    setOrDelete("status", next.status ?? status);
    setOrDelete("min_score", next.min_score ?? minScore);
    setOrDelete("sort", next.sort ?? sort);
    setOrDelete("order", next.order ?? order);
    startTransition(() => {
      router.push(`/products?${params.toString()}`);
    });
  }

  return (
    <div
      className="rounded-2xl bg-card px-5 py-4 flex flex-wrap items-center gap-4"
      style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
      data-testid="products-filter-bar"
    >
      <form
        className="flex items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          apply({ q });
        }}
      >
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索产品名 / URL / 概览"
          aria-label="搜索产品体验报告"
          data-testid="products-filter-search"
          className="bg-secondary/60 text-foreground text-[13px] px-3 py-1.5 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40 min-w-[260px]"
          style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
        />
        <button
          type="submit"
          className="text-[12px] text-primary hover:text-brand-hover px-2.5 py-1 rounded-md"
          style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
          data-testid="products-filter-search-submit"
        >
          搜索
        </button>
      </form>

      <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
        <span className="tracking-wider">状态</span>
        <select
          value={status}
          onChange={(e) => {
            const next = e.target.value;
            setStatus(next);
            apply({ status: next });
          }}
          data-testid="products-filter-status"
          className="bg-secondary/60 text-foreground text-[12px] px-2.5 py-1 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40"
          style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-2 text-[12px] text-muted-foreground">
        <span className="tracking-wider">最低分</span>
        <select
          value={minScore}
          onChange={(e) => {
            const next = e.target.value;
            setMinScore(next);
            apply({ min_score: next });
          }}
          data-testid="products-filter-min-score"
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
          data-testid="products-filter-sort"
          className="bg-secondary/60 text-foreground text-[12px] px-2.5 py-1 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40"
          style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
        >
          <option value="started_at">开始时间</option>
          <option value="completed_at">完成时间</option>
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
          data-testid="products-filter-order"
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
