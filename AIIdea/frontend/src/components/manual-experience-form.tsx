"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import { triggerExperienceUrl, ApiError } from "@/lib/api";

export function ManualExperienceForm() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [requiresLogin, setRequiresLogin] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!url.trim()) {
      setError("请输入产品 URL");
      return;
    }
    startTransition(async () => {
      try {
        const res = await triggerExperienceUrl({
          url: url.trim(),
          name: name.trim() || undefined,
          requires_login: requiresLogin,
        });
        router.push(`/products/${res.report_id}`);
      } catch (e) {
        if (e instanceof ApiError) {
          setError(e.message || "提交失败");
        } else {
          setError("提交失败，请稍后再试");
        }
      }
    });
  }

  return (
    <form
      onSubmit={submit}
      className="rounded-2xl bg-card px-5 py-4 flex flex-wrap items-end gap-4"
      style={{ boxShadow: "0 0 0 1px var(--color-border)" }}
      data-testid="products-manual-experience-form"
    >
      <div className="flex-1 min-w-[260px]">
        <label className="text-[11px] font-medium text-muted-foreground tracking-[0.15em]">
          产品 URL
        </label>
        <input
          type="url"
          required
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com"
          aria-label="产品 URL"
          data-testid="products-manual-url"
          className="mt-1 w-full bg-secondary/60 text-foreground text-[14px] px-3 py-2 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40"
          style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
        />
      </div>

      <div className="min-w-[180px]">
        <label className="text-[11px] font-medium text-muted-foreground tracking-[0.15em]">
          产品名（可选）
        </label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="留空则用域名"
          aria-label="产品名"
          data-testid="products-manual-name"
          className="mt-1 w-full bg-secondary/60 text-foreground text-[14px] px-3 py-2 rounded-md border-0 focus:outline-none focus:ring-1 focus:ring-primary/40"
          style={{ boxShadow: "0 0 0 1px var(--color-ring-warm)" }}
        />
      </div>

      <label className="flex items-center gap-2 text-[12px] text-muted-foreground pb-2">
        <input
          type="checkbox"
          checked={requiresLogin}
          onChange={(e) => setRequiresLogin(e.target.checked)}
          data-testid="products-manual-requires-login"
        />
        尝试 Google 登录
      </label>

      <button
        type="submit"
        disabled={pending}
        data-testid="products-manual-submit"
        className="px-4 py-2 text-[13px] font-medium rounded-md bg-primary text-primary-foreground transition-all disabled:opacity-50 disabled:cursor-not-allowed hover:brightness-95"
      >
        {pending ? "排队中…" : "立即体验"}
      </button>

      {error && (
        <p
          className="basis-full text-[12px] text-destructive"
          data-testid="products-manual-error"
        >
          {error}
        </p>
      )}
      <p className="basis-full text-[11px] text-muted-foreground font-serif italic">
        Codex 会真实打开浏览器深度体验该产品，单次约 3-8 分钟。提交后会自动跳到详情页，刷新可看进度。
      </p>
    </form>
  );
}
