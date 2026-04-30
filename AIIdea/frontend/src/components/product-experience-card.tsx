import Link from "next/link";
import type { ProductExperienceReportListItem } from "@/lib/types";
import { ScoreIndicator } from "./score-indicator";

const LOGIN_LABEL: Record<string, string> = {
  google: "已用 Google 登录",
  failed: "登录失败",
  none: "未登录",
  skipped: "无需登录",
};

const STATUS_LABEL: Record<string, string> = {
  completed: "完成",
  partial: "部分完成",
  failed: "失败",
  running: "运行中",
};

export function ProductExperienceCard({
  item,
}: {
  item: ProductExperienceReportListItem;
}) {
  return (
    // Outer container is a plain div (not <Link>) so the inner product_url
    // anchor can open the original site without being nested inside another
    // anchor (HTML forbids <a> inside <a>; browsers silently flatten it).
    <div
      className="rounded-2xl bg-card px-6 py-5 transition-all hover:bg-secondary/30 group"
      style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
      data-testid={`product-experience-card-${item.product_slug}`}
    >
      <div className="flex justify-between items-start gap-5">
        <div className="flex-1 min-w-0">
          <Link
            href={`/products/${item.id}`}
            className="font-serif text-[20px] text-foreground hover:text-primary transition-colors leading-snug block"
            data-testid={`product-experience-card-title-${item.product_slug}`}
          >
            {item.product_name}
          </Link>
          <div className="flex items-center gap-2 flex-wrap mt-1">
            {item.project_name && (
              <p
                className="text-[11px] font-mono text-muted-foreground"
                data-testid={`product-experience-card-project-name-${item.product_slug}`}
              >
                {item.project_name}
              </p>
            )}
            {item.aijuicer_workflow_id && (
              <span
                className="text-[10px] font-medium tracking-wider px-2 py-0.5 rounded-md"
                style={{
                  color: "#5b6b43",
                  background: "rgba(122, 140, 92, 0.12)",
                  boxShadow: "0 0 0 1px rgba(122, 140, 92, 0.35)",
                }}
                data-testid={`product-experience-card-aijuicer-${item.product_slug}`}
                title={`AIJuicer workflow: ${item.aijuicer_workflow_id}`}
              >
                已入流
              </span>
            )}
          </div>
          <a
            href={item.product_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mt-1 inline-flex items-center gap-1 text-[12px] text-primary hover:text-brand-hover transition-colors break-all"
            title="在新标签页打开产品官网"
            data-testid={`product-experience-card-url-${item.product_slug}`}
          >
            {item.product_url}
            <span aria-hidden="true">↗</span>
          </a>
          {(item.product_thesis || item.summary_zh) && (
            <p className="text-[14px] text-muted-foreground mt-2.5 line-clamp-3 leading-relaxed">
              {item.product_thesis ?? item.summary_zh}
            </p>
          )}
        </div>
        {item.overall_ux_score != null ? (
          <ScoreIndicator score={item.overall_ux_score} />
        ) : (
          <span className="text-[12px] text-muted-foreground font-serif italic shrink-0">
            —
          </span>
        )}
      </div>
      <div className="flex items-center gap-3 mt-4 text-[12px] text-muted-foreground flex-wrap">
        <span className="font-serif italic">
          {item.run_completed_at
            ? new Date(item.run_completed_at).toLocaleString("zh-CN")
            : "进行中"}
        </span>
        <span className="text-border">·</span>
        <span className="font-serif italic">
          {STATUS_LABEL[item.status] ?? item.status}
        </span>
        <span className="text-border">·</span>
        <span className="font-serif italic">
          {LOGIN_LABEL[item.login_used] ?? item.login_used}
        </span>
        {item.screenshots_count > 0 && (
          <>
            <span className="text-border">·</span>
            <span className="font-serif italic">
              {item.screenshots_count} 张截图
            </span>
          </>
        )}
        <span className="text-border">·</span>
        <Link
          href={`/products/${item.id}`}
          className="font-serif italic text-primary hover:text-brand-hover transition-colors"
          data-testid={`product-experience-card-detail-${item.product_slug}`}
        >
          查看详情 →
        </Link>
      </div>
    </div>
  );
}
