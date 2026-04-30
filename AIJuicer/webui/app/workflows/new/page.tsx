"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { STEPS, createWorkflow, stepLabel } from "@/lib/api";
import { slugifyIdea } from "@/lib/slug";
import { JuicerSpinner } from "@/components/juicer-spinner";

const DEFAULT_INPUT = "demo topic";

export default function NewWorkflow() {
  const router = useRouter();
  const [name, setName] = useState("demo");
  const [input, setInput] = useState(DEFAULT_INPUT);
  // 想法名称（项目 slug）：默认从想法描述自动推；用户改过一次后不再覆盖。
  const [projectName, setProjectName] = useState(() => slugifyIdea(DEFAULT_INPUT));
  const [projectNameDirty, setProjectNameDirty] = useState(false);
  const [policy, setPolicy] = useState<Record<string, "auto" | "manual">>({
    requirement: "auto",
    plan: "auto",
    design: "auto",
    devtest: "auto",
    deploy: "auto",
  });
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  function onInputChange(v: string) {
    setInput(v);
    if (!projectNameDirty) setProjectName(slugifyIdea(v));
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setSubmitting(true);
    try {
      const wf = await createWorkflow({
        name,
        project_name: projectName,
        input: { text: input },
        approval_policy: policy,
      });
      router.push(`/workflows/${wf.id}`);
    } catch (e: any) {
      setErr(e.message ?? String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">新建工作流</h1>
      <form onSubmit={onSubmit} className="card space-y-4 p-6">
        <label className="block space-y-1">
          <span className="text-sm font-medium">项目标题</span>
          <input
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </label>

        <label className="block space-y-1">
          <span className="text-sm font-medium">想法名称</span>
          <input
            className="w-full rounded-md border border-slate-300 px-3 py-2 font-mono text-sm"
            value={projectName}
            onChange={(e) => {
              setProjectName(e.target.value);
              setProjectNameDirty(true);
            }}
            pattern="[a-z0-9][a-z0-9-]*"
            maxLength={80}
            placeholder="ai-email-classifier"
            required
          />
          <p className="text-xs text-slate-500">
            小写英文 + 数字 + 短横线，作为项目目录 / 仓库名用。撞名时调度器会自动加 4 位随机后缀。
          </p>
        </label>

        <label className="block space-y-1">
          <span className="text-sm font-medium">想法描述</span>
          <textarea
            className="h-32 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            value={input}
            onChange={(e) => onInputChange(e.target.value)}
            placeholder="用一句话或一段话说清楚你想做什么。例如：做一个面向大学生的 AI 课程笔记助手。"
            required
          />
        </label>

        <div className="space-y-2">
          <span className="text-sm font-medium">审批策略</span>
          <div className="grid grid-cols-3 gap-2 text-sm">
            {STEPS.filter((s) => s !== "idea").map((step) => (
              <label key={step} className="flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5">
                <span className="flex-1 text-xs">{stepLabel(step)}</span>
                <select
                  className="rounded bg-white px-1 py-0.5 text-xs"
                  value={policy[step] ?? "manual"}
                  onChange={(e) =>
                    setPolicy({ ...policy, [step]: e.target.value as "auto" | "manual" })
                  }
                >
                  <option value="auto">自动</option>
                  <option value="manual">人工</option>
                </select>
              </label>
            ))}
          </div>
          <p className="text-xs text-slate-500">
            自动：调度器完成上一步后直接推进；人工：停在"等待审批"状态，由你在详情页点"批准"继续。
          </p>
        </div>

        {err && <div className="rounded bg-rose-50 px-3 py-2 text-sm text-rose-700">{err}</div>}

        <div className="flex gap-2">
          <button type="submit" className="btn btn-primary" disabled={submitting}>
            {submitting ? (
              <>
                <JuicerSpinner size={14} />
                提交中…
              </>
            ) : (
              "提交"
            )}
          </button>
          <button type="button" className="btn" onClick={() => router.push("/")}>
            取消
          </button>
        </div>
      </form>
    </div>
  );
}
