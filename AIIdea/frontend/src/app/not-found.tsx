import Link from "next/link";

export default function GlobalNotFound() {
  return (
    <div
      className="max-w-xl mx-auto py-24 text-center space-y-6"
      data-testid="not-found-page"
    >
      <p className="text-[11px] font-medium tracking-[0.2em] text-muted-foreground">
        404
      </p>
      <h1 className="font-serif text-[40px] text-foreground leading-tight">
        页面不存在
      </h1>
      <p className="text-[15px] text-muted-foreground">
        抱歉，你访问的页面已经移动或从未存在。
      </p>
      <div>
        <Link
          href="/"
          className="text-[13px] text-primary hover:text-brand-hover transition-colors"
          data-testid="not-found-home-link"
        >
          ← 回到仪表盘
        </Link>
      </div>
    </div>
  );
}
