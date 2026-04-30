import Link from "next/link";

export default function SourceNotFound() {
  return (
    <div
      className="max-w-xl mx-auto py-24 text-center space-y-6"
      data-testid="source-not-found"
    >
      <p className="text-[11px] font-medium tracking-[0.2em] text-muted-foreground">
        404
      </p>
      <h1 className="font-serif text-[40px] text-foreground leading-tight">
        条目不存在
      </h1>
      <p className="text-[15px] text-muted-foreground">
        这个数据条目可能已被删除或 ID 不正确。
      </p>
      <div>
        <Link
          href="/sources"
          className="text-[13px] text-primary hover:text-brand-hover transition-colors"
          data-testid="source-not-found-back"
        >
          ← 返回数据列表
        </Link>
      </div>
    </div>
  );
}
