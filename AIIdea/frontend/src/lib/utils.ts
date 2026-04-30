import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Format a date as a relative phrase in Chinese, e.g. "3 分钟前", "2 小时前", "昨天".
 * Falls back to an absolute zh-CN datetime string for dates older than a week.
 */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const now = Date.now();
  const diffMs = now - d.getTime();
  if (diffMs < 0) return d.toLocaleString("zh-CN");
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `${sec} 秒前`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  if (day === 1) return "昨天";
  if (day < 7) return `${day} 天前`;
  return d.toLocaleString("zh-CN");
}

/**
 * Future-relative phrasing for scheduled times, e.g. "3 分钟后".
 */
export function formatFutureRelative(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const diffMs = d.getTime() - Date.now();
  if (diffMs <= 0) return "即将运行";
  const sec = Math.floor(diffMs / 1000);
  if (sec < 60) return `${sec} 秒后`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} 分钟后`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时后`;
  const day = Math.floor(hr / 24);
  return `${day} 天后`;
}


/**
 * Localized label for AnalysisResult.product_type. Falls back to the raw
 * value (or "—") when the enum drifts.
 */
const PRODUCT_TYPE_LABELS: Record<string, string> = {
  web: "网站",
  saas: "SaaS",
  mobile_app: "移动 App",
  chrome_extension: "浏览器插件",
  api: "API",
  sdk: "SDK",
  ai_app: "AI 应用",
  bot: "聊天机器人",
  cli: "CLI",
  desktop: "桌面应用",
};

export function productTypeLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return PRODUCT_TYPE_LABELS[value] ?? value;
}
