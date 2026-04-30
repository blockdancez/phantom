import Link from "next/link";

type Props = {
  page: number;
  pageSize: number;
  total: number;
  baseQuery: URLSearchParams;
};

export function Pagination({ page, pageSize, total, baseQuery }: Props) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  if (totalPages <= 1)
    return (
      <div className="flex justify-between px-4 py-2 text-xs text-slate-500">
        <span>共 {total} 条</span>
        <span>第 {page} / {totalPages} 页 · 每页 {pageSize}</span>
      </div>
    );

  function href(p: number): string {
    const q = new URLSearchParams(baseQuery);
    if (p <= 1) q.delete("page");
    else q.set("page", String(p));
    const qs = q.toString();
    return qs ? `/workflows?${qs}` : "/workflows";
  }

  // 最多显示 7 个页码（首 / 末 / 当前 ±2）
  const shown: (number | "…")[] = [];
  const window = new Set<number>();
  window.add(1);
  window.add(totalPages);
  for (let p = page - 2; p <= page + 2; p++) {
    if (p >= 1 && p <= totalPages) window.add(p);
  }
  const sorted = Array.from(window).sort((a, b) => a - b);
  let last = 0;
  for (const n of sorted) {
    if (last && n > last + 1) shown.push("…");
    shown.push(n);
    last = n;
  }

  const prevDisabled = page <= 1;
  const nextDisabled = page >= totalPages;

  return (
    <div className="flex items-center justify-between gap-2 px-4 py-2 text-xs">
      <span className="text-slate-500">
        共 {total} 条 · 第 {page} / {totalPages} 页 · 每页 {pageSize}
      </span>
      <div className="flex items-center gap-1">
        <Link
          href={prevDisabled ? "#" : href(page - 1)}
          aria-disabled={prevDisabled}
          className={`btn px-2 py-0.5 text-xs ${prevDisabled ? "pointer-events-none opacity-40" : ""}`}
        >
          ‹ 上一页
        </Link>
        {shown.map((n, i) =>
          n === "…" ? (
            <span key={`e${i}`} className="px-2 text-slate-400">
              …
            </span>
          ) : (
            <Link
              key={n}
              href={href(n)}
              className={`btn px-2 py-0.5 text-xs ${
                n === page ? "border-brand-500 bg-brand-500/10 text-brand-700" : ""
              }`}
            >
              {n}
            </Link>
          ),
        )}
        <Link
          href={nextDisabled ? "#" : href(page + 1)}
          aria-disabled={nextDisabled}
          className={`btn px-2 py-0.5 text-xs ${nextDisabled ? "pointer-events-none opacity-40" : ""}`}
        >
          下一页 ›
        </Link>
      </div>
    </div>
  );
}
