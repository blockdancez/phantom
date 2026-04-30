"use client";

import { useEffect, useState } from "react";
import { stepLabel } from "@/lib/api";

/** 该 step 上一次的反馈。`user_feedback` 现在是 { [step]: string } 字典；
 * 历史 string 形式不属于任何具体 step，按缺失处理。 */
function feedbackForStep(input: Record<string, unknown>, step: string): string | null {
  const fb = input.user_feedback;
  if (fb && typeof fb === "object" && !Array.isArray(fb)) {
    const v = (fb as Record<string, unknown>)[step];
    if (typeof v === "string" && v.trim()) return v;
  }
  return null;
}

type Props = {
  step: string;
  initialInput: Record<string, unknown>;
  onCancel: () => void;
  /**
   * confirm 时把"对话框里的内容"作为重跑指令传给 Agent。
   * 父组件负责调 submitApproval：
   *   modified_input.user_feedback[step] = instruction
   *   comment                            = instruction
   */
  onConfirm: (instruction: string) => Promise<void>;
};

export function RerunDialog({ step, initialInput, onCancel, onConfirm }: Props) {
  const [instruction, setInstruction] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      await onConfirm(instruction.trim());
    } catch (e: any) {
      setErr(e.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  const feedback = feedbackForStep(initialInput, step);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={onCancel}
    >
      <div
        className="card flex max-h-[90vh] w-full max-w-xl flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="text-base font-semibold">
            重新执行 · <span className="text-brand-700">{stepLabel(step)}</span>
          </h2>
          <button className="btn text-sm" onClick={onCancel}>
            ✕
          </button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {feedback && (
            <section>
              <div className="mb-1 text-sm font-medium">
                上次反馈
                <span className="ml-2 text-xs text-slate-400">
                  （仅 {stepLabel(step)} 步骤）
                </span>
              </div>
              <article className="prose prose-slate max-w-none whitespace-pre-wrap rounded border border-slate-200 bg-white p-3 text-sm">
                {feedback}
              </article>
            </section>
          )}

          <section>
            <div className="mb-1 text-sm font-medium">
              重跑指令
              <span className="ml-2 text-xs text-slate-400">
                作为 input.user_feedback 传给 {stepLabel(step)} agent
              </span>
            </div>
            <textarea
              autoFocus
              rows={6}
              placeholder="例如：标题再短一点，受众改成大学生，去掉关于价格的部分…"
              className="w-full rounded border border-slate-300 bg-white p-2 text-sm"
              value={instruction}
              onChange={(e) => setInstruction(e.target.value)}
            />
            <div className="mt-1 text-xs text-slate-400">
              首次输出 / 上次输出对比已挪到工作流详情页"产物对比"面板。
            </div>
          </section>

          {err && (
            <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-4 py-3">
          <button className="btn" onClick={onCancel} disabled={busy}>
            取消
          </button>
          <button className="btn btn-primary" onClick={submit} disabled={busy}>
            {busy ? "提交中…" : "确认重跑"}
          </button>
        </div>
      </div>
    </div>
  );
}
