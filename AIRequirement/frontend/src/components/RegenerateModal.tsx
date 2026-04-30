import { useEffect, useRef, useState } from "react";

interface Props {
  ideaContent: string;
  onConfirm: (instruction: string | undefined) => Promise<void>;
  onClose: () => void;
}

export default function RegenerateModal({ ideaContent, onConfirm, onClose }: Props) {
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    textareaRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [busy, onClose]);

  const handleSubmit = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm(instruction.trim() || undefined);
    } catch (e) {
      setError((e as Error).message || "重新生成失败，请稍后重试");
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      role="dialog"
      aria-modal="true"
    >
      <div
        className="absolute inset-0 bg-near-black/30 backdrop-blur-sm"
        onClick={() => !busy && onClose()}
      />

      <div className="relative w-full max-w-lg bg-ivory rounded-2xl shadow-[0_20px_60px_-15px_rgba(20,20,19,0.25),0_0_0_1px_var(--color-border-warm)] overflow-hidden modal-enter">
        <div className="px-6 pt-6 pb-4 border-b border-[var(--color-border-cream)]">
          <h2 className="font-serif text-xl text-near-black">重新生成需求文档</h2>
          <p className="text-xs text-stone mt-1.5 leading-relaxed">
            将用相同 idea 重跑研究 + 写作流程；新版本会替换原有文档。
          </p>
        </div>

        <div className="px-6 py-5 space-y-4">
          <div>
            <div className="text-[11px] uppercase tracking-wider text-stone mb-1.5">
              原始 Idea
            </div>
            <p className="text-sm text-charcoal leading-relaxed line-clamp-2 bg-parchment/60 rounded-lg px-3 py-2 border border-[var(--color-border-cream)]">
              {ideaContent}
            </p>
          </div>

          <div>
            <label className="block text-[11px] uppercase tracking-wider text-stone mb-1.5">
              重跑指令 <span className="text-stone/70 normal-case tracking-normal">（可选）</span>
            </label>
            <textarea
              ref={textareaRef}
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              disabled={busy}
              rows={4}
              maxLength={2000}
              placeholder="例如：请把目标用户聚焦到 B 端 SaaS 决策者；强化 MVP 范围中的数据看板能力。"
              className="w-full bg-parchment/60 border border-[var(--color-border-warm)] rounded-lg px-3 py-2.5 text-sm text-near-black placeholder:text-warm-silver focus:outline-none focus:border-terracotta focus:bg-ivory transition-colors resize-none disabled:opacity-60"
            />
            <div className="flex justify-between mt-1.5">
              <span className="text-[11px] text-stone/80">⌘/Ctrl + Enter 提交</span>
              <span className="text-[11px] text-stone/80 tabular-nums">
                {instruction.length}/2000
              </span>
            </div>
          </div>

          {error && (
            <div className="text-sm text-terracotta bg-terracotta/10 border border-terracotta/20 rounded-lg px-3 py-2">
              {error}
            </div>
          )}
        </div>

        <div className="px-6 py-4 bg-parchment/40 border-t border-[var(--color-border-cream)] flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="px-4 py-2 text-sm text-charcoal hover:bg-sand/60 rounded-lg transition-colors disabled:opacity-50"
          >
            取消
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={busy}
            className="px-4 py-2 text-sm font-medium text-ivory bg-terracotta hover:bg-terracotta-hover rounded-lg transition-colors disabled:opacity-60 disabled:cursor-not-allowed inline-flex items-center gap-2"
          >
            {busy && (
              <span className="inline-block w-3.5 h-3.5 border-2 border-ivory/40 border-t-ivory rounded-full animate-spin" />
            )}
            {busy ? "提交中..." : "确认重新生成"}
          </button>
        </div>
      </div>
    </div>
  );
}
