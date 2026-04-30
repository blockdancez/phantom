import Link from "next/link";

export default function AnalysisNotFound() {
  return (
    <div
      className="max-w-xl mx-auto py-24 text-center space-y-6"
      data-testid="analysis-not-found"
    >
      <p className="text-[11px] font-medium tracking-[0.2em] text-muted-foreground">
        404
      </p>
      <h1 className="font-serif text-[40px] text-foreground leading-tight">
        分析不存在
      </h1>
      <p className="text-[15px] text-muted-foreground">
        找不到该分析结果，可能已被删除或 ID 不正确。
      </p>
      <div>
        <Link
          href="/analysis"
          className="text-[13px] text-primary hover:text-brand-hover transition-colors"
          data-testid="analysis-not-found-back"
        >
          ← 返回分析列表
        </Link>
      </div>
    </div>
  );
}
