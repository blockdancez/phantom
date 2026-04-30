/**
 * 产物相关的共享工具函数。
 *
 * 多个组件需要做同样的"这是不是文本/markdown/url、这是不是 .first.* 副本、是否
 * 该展示给用户"的判断；以前散落在 ArtifactViewer / RerunDialog / 详情页里。
 * 统一到这里，避免漂移。
 */

import { Artifact, STEPS } from "@/lib/api";

export type ArtifactKind =
  | "markdown"
  | "json"
  | "text"
  | "image"
  | "html"
  | "url"
  | "binary";

export function kind(ct: string | null | undefined, key: string): ArtifactKind {
  const ext = key.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "url" || ct === "text/uri-list" || ct === "text/x-url") return "url";
  if (ext === "md" || ct === "text/markdown") return "markdown";
  if (ext === "json" || ct === "application/json") return "json";
  if (ext === "html" || ct === "text/html") return "html";
  if (
    ["png", "jpg", "jpeg", "gif", "svg"].includes(ext) ||
    (ct ?? "").startsWith("image/")
  )
    return "image";
  if (
    (ct ?? "").startsWith("text/") ||
    ["txt", "py", "yml", "yaml", "log"].includes(ext)
  )
    return "text";
  return "binary";
}

/** 把同一 (step, key) 的多个 attempt 聚成 [最早, 最晚]。
 *  没有任何 artifact 时返回 [null, null]；只有一次 attempt 时 first === last。 */
export function pickFirstAndLast(
  artifacts: Artifact[],
): { first: Artifact | null; last: Artifact | null } {
  if (artifacts.length === 0) return { first: null, last: null };
  const sorted = [...artifacts].sort((a, b) => a.attempt - b.attempt);
  return { first: sorted[0], last: sorted[sorted.length - 1] };
}

/** 同 (step, key) 取 attempt 最大的那一份；用于产物列表"每个 key 只显示最新一行"。 */
export function dedupeByKeyKeepLatest(artifacts: Artifact[]): Artifact[] {
  const m = new Map<string, Artifact>();
  for (const a of artifacts) {
    const k = `${a.step}|${a.key}`;
    const cur = m.get(k);
    if (!cur || a.attempt > cur.attempt) m.set(k, a);
  }
  return Array.from(m.values());
}

/** 适合给用户阅读的产物：排除 application/json sidecar 之类的元数据。 */
export function isReadable(a: Artifact): boolean {
  const ct = (a.content_type ?? "").toLowerCase();
  const ext = a.key.split(".").pop()?.toLowerCase() ?? "";
  if (ct.includes("json") || ext === "json") return false;
  if (ct.startsWith("application/")) return false;
  return true;
}

/** 文本 / markdown / url / json / html → 可在 diff 视图里以字符串方式对比。 */
export function isComparable(a: Artifact): boolean {
  const k = kind(a.content_type, a.key);
  return k !== "image" && k !== "binary";
}

/**
 * 由 workflow status / failed_step 推出"用户视角下的活跃 step"，用于产物对比面板
 * 默认选中哪一步：
 * - <STEP>_RUNNING / <STEP>_DONE → 该 step
 * - AWAITING_APPROVAL_<NEXT>     → 上一步（刚产出待审）
 * - AWAITING_MANUAL_ACTION       → failed_step
 * - COMPLETED                    → 最后一步（deploy）
 * - ABORTED                      → failed_step（如有）
 */
export function inferActiveStep(
  status: string,
  failedStep: string | null,
): string | null {
  if (status === "COMPLETED") return STEPS[STEPS.length - 1] ?? null;
  if (status === "ABORTED" || status === "AWAITING_MANUAL_ACTION") return failedStep;
  const m = status.match(/^([A-Z]+)_(RUNNING|DONE)$/);
  if (m) return m[1].toLowerCase();
  if (status.startsWith("AWAITING_APPROVAL_")) {
    const next = status.replace("AWAITING_APPROVAL_", "").toLowerCase();
    const idx = STEPS.indexOf(next);
    if (idx > 0) return STEPS[idx - 1];
  }
  return null;
}
