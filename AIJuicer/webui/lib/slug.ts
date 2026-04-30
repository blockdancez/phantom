/**
 * 从 idea 文本提取项目 slug。
 *
 * 规则跟 SDK `aijuicer_sdk.slugify_idea` 对齐：
 * - 抓 a-zA-Z0-9 序列，最多前 3 个去重单词
 * - 全部小写 + 短横线连接
 * - 长度上限 40，提取不出英文词时回落到 "project"
 *
 * 撞名由 scheduler 处理（自动加 4 位随机后缀），caller 不必查重。
 */
const MAX_LEN = 40;
const MAX_WORDS = 3;

export function slugifyIdea(text: string | null | undefined): string {
  if (!text) return "project";
  const words = text.match(/[A-Za-z][A-Za-z0-9]*|[0-9]+/g) ?? [];
  const cleaned: string[] = [];
  const seen = new Set<string>();
  for (const w of words) {
    const lw = w.toLowerCase();
    if (seen.has(lw)) continue;
    cleaned.push(lw);
    seen.add(lw);
    if (cleaned.length >= MAX_WORDS) break;
  }
  if (cleaned.length === 0) return "project";
  const slug = cleaned.join("-").slice(0, MAX_LEN).replace(/-+$/, "");
  if (slug.length < 2) return "project";
  return slug;
}
