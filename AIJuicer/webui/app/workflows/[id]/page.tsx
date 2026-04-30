"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  Artifact,
  HistoryEntry,
  Workflow,
  artifactContentUrl,
  deleteWorkflow,
  getWorkflow,
  listArtifacts,
  listWorkflowHistory,
  prevStep,
  statusLabel,
  stepLabel,
  submitApproval,
  workflowEventsUrl,
} from "@/lib/api";
import { dedupeByKeyKeepLatest, inferActiveStep } from "@/lib/artifact";
import { ArtifactCompare } from "@/components/artifact-compare";
import Dag from "@/components/dag";
import { HistoryPanel } from "@/components/history-panel";
import { JuicerSpinner } from "@/components/juicer-spinner";
import { RerunDialog } from "@/components/rerun-dialog";

export default function WorkflowDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [wf, setWf] = useState<Workflow | null>(null);
  const [arts, setArts] = useState<Artifact[]>([]);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [rerunFor, setRerunFor] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [w, a, h] = await Promise.all([
        getWorkflow(id),
        listArtifacts(id),
        listWorkflowHistory(id).catch(() => [] as HistoryEntry[]),
      ]);
      setWf(w);
      setArts(a);
      setHistory(h);
    } catch (e: any) {
      setErr(e.message ?? String(e));
    }
  }, [id]);

  useEffect(() => {
    refresh();
    if (rerunFor) return; // 弹窗打开时暂停轮询，避免引用刷新干扰输入
    const t = setInterval(refresh, 3000);
    return () => clearInterval(t);
  }, [refresh, rerunFor]);

  // SSE 仅用于"立即触发 refresh"，不再渲染时间线
  useEffect(() => {
    const es = new EventSource(workflowEventsUrl(id));
    const trigger = () => refresh();
    for (const ev of [
      "state.changed",
      "task.succeeded",
      "task.failed",
      "task.retried",
    ]) {
      es.addEventListener(ev, trigger);
    }
    return () => es.close();
  }, [id, refresh]);

  async function doApproval(decision: string, step?: string) {
    setBusy(true);
    try {
      await submitApproval(id, { decision, step });
      await refresh();
    } catch (e: any) {
      setErr(e.message ?? String(e));
    } finally {
      setBusy(false);
    }
  }

  if (err) return <div className="card p-4 text-sm text-rose-700">错误：{err}</div>;
  if (!wf)
    return (
      <div className="flex justify-center py-16">
        <JuicerSpinner size={40} label="加载中…" />
      </div>
    );

  const awaitingStep = wf.status.startsWith("AWAITING_APPROVAL_")
    ? wf.status.replace("AWAITING_APPROVAL_", "").toLowerCase()
    : null;
  const rerunTargetOnReject = awaitingStep ? prevStep(awaitingStep) : null;
  const canApprove = awaitingStep !== null;
  // 第一步（想法）不展示"重新执行"——它没有上游、没有可比对的版本，
  // 想换内容就直接编辑产物或新建工作流。仅在 prev_step 不是 idea 时才显示按钮。
  const canRerunOnReject =
    rerunTargetOnReject !== null && rerunTargetOnReject !== "idea";
  const canSkip = wf.status === "AWAITING_MANUAL_ACTION";
  const canRerunFailed = wf.status === "AWAITING_MANUAL_ACTION" && wf.failed_step;
  const isTerminal = wf.status === "COMPLETED" || wf.status === "ABORTED";
  // .first.* 只为对比保留，不在产物列表里展示
  // 列表里每个 (step, key) 只展示最新 attempt 的那一行；旧版 .first.* 副本（迁移
  // 0004 之前 example agents 写的）继续过滤掉，避免历史噪音
  const visibleArts = dedupeByKeyKeepLatest(
    arts.filter((a) => !/\.first(\.|$)/.test(a.key)),
  );
  const activeStep = inferActiveStep(wf.status, wf.failed_step);

  async function onDelete() {
    if (!confirm(`确定删除工作流"${wf!.name}"吗？此操作不可恢复。`)) return;
    try {
      await deleteWorkflow(wf!.id);
      router.push("/");
    } catch (e: any) {
      setErr(e.message ?? String(e));
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">{wf.name}</h1>
          {wf.project_name && (
            <div className="mt-1">
              <span className="badge border-violet-200 bg-violet-50 font-mono text-violet-700">
                项目：{wf.project_name}
              </span>
            </div>
          )}
          <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
            <span className="font-mono">{wf.id}</span>
            <span>·</span>
            <span>{new Date(wf.created_at).toLocaleString()}</span>
          </div>
        </div>
        <div className="flex gap-2">
          <button className="btn" onClick={() => router.push("/")}>
            ← 返回列表
          </button>
          <button className="btn btn-danger" onClick={onDelete}>
            删除
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="badge gap-1.5">
          {wf.status.endsWith("_RUNNING") && <JuicerSpinner size={14} />}
          状态：<span className="ml-1 font-medium">{statusLabel(wf.status)}</span>
          <span className="ml-1 font-mono text-[10px] text-slate-400">{wf.status}</span>
        </span>
        {wf.current_step && (
          <span className="badge">
            当前步骤：<span className="ml-1 font-medium">{stepLabel(wf.current_step)}</span>
          </span>
        )}
        {wf.failed_step && (
          <span className="badge border-rose-200 bg-rose-50 text-rose-700">
            失败步骤：<span className="ml-1 font-medium">{stepLabel(wf.failed_step)}</span>
          </span>
        )}
      </div>

      <Dag status={wf.status} failedStep={wf.failed_step} />

      {/* 操作面板 */}
      {!isTerminal && (
        <div className="card p-3">
          <div className="mb-2 text-sm font-medium">操作</div>
          <div className="flex flex-wrap gap-2 text-sm">
            {canApprove && (
              <button
                disabled={busy}
                className="btn btn-primary"
                onClick={() => doApproval("approve", awaitingStep!)}
                title={`批准 ${stepLabel(rerunTargetOnReject)} 的产出 → 进入 ${stepLabel(awaitingStep)}`}
              >
                批准 {stepLabel(rerunTargetOnReject)} → 进入 {stepLabel(awaitingStep)}
              </button>
            )}
            {canRerunOnReject && (
              <button
                disabled={busy}
                className="btn"
                onClick={() => setRerunFor(rerunTargetOnReject!)}
              >
                重新执行 {stepLabel(rerunTargetOnReject)}
              </button>
            )}
            {canRerunFailed && wf.failed_step && (
              <button
                disabled={busy}
                className="btn"
                onClick={() => setRerunFor(wf.failed_step!)}
              >
                重跑 {stepLabel(wf.failed_step)}
              </button>
            )}
            {canSkip && (
              <button
                disabled={busy}
                className="btn"
                onClick={() => doApproval("skip")}
              >
                跳过失败步骤
              </button>
            )}
            <button
              disabled={busy}
              className="btn btn-danger"
              onClick={() => doApproval("abort")}
            >
              中止工作流
            </button>
          </div>
        </div>
      )}

      {/* 产物对比 —— 占满整宽，替代之前的产物预览 + 事件时间线 */}
      <ArtifactCompare
        artifacts={arts}
        defaultStep={activeStep}
        onArtifactEdited={refresh}
      />

      {/* 产物列表（点击=直接打开内容） */}
      <div className="card p-4">
        <h2 className="mb-2 text-sm font-semibold">
          产物列表（共 {visibleArts.length} 个）
        </h2>
        {visibleArts.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-slate-400">
            {!isTerminal && <JuicerSpinner size={16} />}
            <span>{isTerminal ? "无产物" : "等待 agent 榨出产物…"}</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
            {visibleArts.map((a) => (
              <a
                key={a.id}
                href={artifactContentUrl(a.id)}
                target="_blank"
                rel="noreferrer"
                className="block rounded-md border border-slate-200 bg-white px-3 py-2 text-left text-sm hover:bg-slate-50"
              >
                <div className="text-xs text-slate-500">{stepLabel(a.step)}</div>
                <div className="truncate font-medium">{a.key}</div>
                <div className="text-[11px] text-slate-400">
                  {a.size_bytes}B · {a.content_type ?? "?"}
                </div>
              </a>
            ))}
          </div>
        )}
      </div>

      {/* 修改 / 重跑 历史 */}
      <div className="card overflow-hidden">
        <div className="border-b border-slate-200 px-4 py-3">
          <h2 className="text-sm font-semibold">
            修改 / 重跑 历史
            <span className="ml-2 text-xs text-slate-400">共 {history.length} 条</span>
          </h2>
        </div>
        <HistoryPanel entries={history} />
      </div>

      {/* 输入参数 / 审批策略：折叠 */}
      <div className="card p-4">
        <details>
          <summary className="cursor-pointer text-sm font-medium text-slate-700">
            输入参数 / 审批策略
          </summary>
          <div className="mt-3 space-y-3">
            <div>
              <div className="mb-1 text-xs text-slate-500">input</div>
              <pre className="code">{JSON.stringify(wf.input, null, 2)}</pre>
            </div>
            <div>
              <div className="mb-1 text-xs text-slate-500">approval_policy</div>
              <pre className="code">{JSON.stringify(wf.approval_policy, null, 2)}</pre>
            </div>
          </div>
        </details>
      </div>

      {rerunFor && (
        <RerunDialog
          step={rerunFor}
          initialInput={wf.input}
          onCancel={() => setRerunFor(null)}
          onConfirm={async (instruction) => {
            const prev =
              wf.input.user_feedback &&
              typeof wf.input.user_feedback === "object" &&
              !Array.isArray(wf.input.user_feedback)
                ? (wf.input.user_feedback as Record<string, unknown>)
                : {};
            const modifiedInput = instruction
              ? { ...wf.input, user_feedback: { ...prev, [rerunFor]: instruction } }
              : wf.input;
            try {
              await submitApproval(id, {
                decision: "rerun",
                step: rerunFor,
                modified_input: modifiedInput,
                comment: instruction || undefined,
              });
              setRerunFor(null);
              await refresh();
            } catch (e: any) {
              setErr(e.message ?? String(e));
              throw e;
            }
          }}
        />
      )}
    </div>
  );
}
