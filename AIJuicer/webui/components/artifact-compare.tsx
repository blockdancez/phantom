"use client";

import { useEffect, useMemo, useState } from "react";
import ReactDiffViewer from "react-diff-viewer-continued";
import {
  Artifact,
  STEPS,
  artifactContentUrl,
  stepLabel,
} from "@/lib/api";
import { isComparable, isReadable, kind, pickFirstAndLast } from "@/lib/artifact";
import { ArtifactEditDialog } from "@/components/artifact-edit-dialog";
import { ArtifactViewer } from "@/components/artifact-viewer";
import { JuicerSpinner } from "@/components/juicer-spinner";

type Mode = "render" | "diff";

export function ArtifactCompare({
  artifacts,
  defaultStep,
  onArtifactEdited,
}: {
  artifacts: Artifact[];
  defaultStep: string | null;
  /** ArtifactViewer 编辑保存后用于触发父级 refresh */
  onArtifactEdited?: () => void;
}) {
  // 各 step 有产物的列表，供 tab 行显示哪些可点
  const stepHasArt = useMemo(() => {
    const m: Record<string, boolean> = {};
    for (const a of artifacts) m[a.step] = true;
    return m;
  }, [artifacts]);

  const [step, setStep] = useState<string | null>(defaultStep);
  const [mode, setMode] = useState<Mode>("render");
  const [editing, setEditing] = useState(false);

  // defaultStep 变化（工作流推进 / 重跑）时跟随；用户手动切过就别覆盖
  const [userPickedStep, setUserPickedStep] = useState(false);
  useEffect(() => {
    if (userPickedStep) return;
    if (defaultStep && defaultStep !== step) setStep(defaultStep);
  }, [defaultStep, step, userPickedStep]);

  // 该 step 所有可读 artifact（多 attempt + 多 key），按 (key, attempt) 全展开
  const stepArts = useMemo(
    () => (step ? artifacts.filter((a) => a.step === step && isReadable(a)) : []),
    [artifacts, step],
  );
  // 默认对比"主产物"——按 key 分组里 attempt 最少的当 first、最大的当 last。
  // 多 key 时取第一个 key 的（这一步通常只有一个主 markdown / url）
  const { firstArt, lastArt } = useMemo(() => {
    if (stepArts.length === 0) return { firstArt: null, lastArt: null };
    // 把同一 key 的多次 attempt 聚合，挑第一组（一般 step 只有一个主产物 key）
    const byKey = new Map<string, Artifact[]>();
    for (const a of stepArts) {
      const arr = byKey.get(a.key) ?? [];
      arr.push(a);
      byKey.set(a.key, arr);
    }
    const firstKey = stepArts[0].key;
    const { first, last } = pickFirstAndLast(byKey.get(firstKey) ?? []);
    return { firstArt: first, lastArt: last };
  }, [stepArts]);

  const canDiff =
    firstArt !== null &&
    lastArt !== null &&
    isComparable(firstArt) &&
    isComparable(lastArt);
  const canEdit = lastArt !== null && isComparable(lastArt);

  // 切到一个不可 diff 的 step → 回退到 render
  useEffect(() => {
    if (mode === "diff" && !canDiff) setMode("render");
  }, [canDiff, mode]);

  return (
    <div className="card overflow-hidden">
      {/* 顶部：step tabs + mode 切换 */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {STEPS.map((s) => {
            const has = stepHasArt[s];
            const active = step === s;
            return (
              <button
                key={s}
                disabled={!has}
                onClick={() => {
                  setStep(s);
                  setUserPickedStep(true);
                }}
                className={`btn px-2 py-0.5 text-xs ${
                  active
                    ? "border-brand-500 bg-brand-500/10 text-brand-700"
                    : has
                      ? ""
                      : "pointer-events-none opacity-40"
                }`}
                title={has ? undefined : "该步骤暂无产物"}
              >
                {stepLabel(s)}
              </button>
            );
          })}
        </div>
        <div className="flex gap-1 text-xs">
          <button
            onClick={() => setMode("render")}
            className={`btn px-2 py-0.5 ${
              mode === "render" ? "border-brand-500 bg-brand-500/10 text-brand-700" : ""
            }`}
          >
            渲染
          </button>
          <button
            onClick={() => setMode("diff")}
            disabled={!canDiff}
            title={!canDiff ? "缺少首次输出快照或产物为二进制，无法对比" : undefined}
            className={`btn px-2 py-0.5 ${
              mode === "diff" ? "border-brand-500 bg-brand-500/10 text-brand-700" : ""
            } ${!canDiff ? "pointer-events-none opacity-40" : ""}`}
          >
            对比
          </button>
          <span className="mx-1 text-slate-300">|</span>
          <button
            onClick={() => setEditing(true)}
            disabled={!canEdit}
            title={
              !canEdit
                ? "二进制 / 当前无产物，不可编辑"
                : `编辑 ${lastArt!.step} / ${lastArt!.key}`
            }
            className={`btn px-2 py-0.5 ${!canEdit ? "pointer-events-none opacity-40" : ""}`}
          >
            ✎ 编辑
          </button>
        </div>
      </div>

      {/* 主体 */}
      <div className="p-4">
        {step === null || stepArts.length === 0 ? (
          <div className="flex h-48 items-center justify-center text-sm text-slate-400">
            {step ? `${stepLabel(step)} 步骤暂无产物` : "请选择一个步骤"}
          </div>
        ) : mode === "render" ? (
          <RenderMode firstArt={firstArt} lastArt={lastArt} stepArts={stepArts} />
        ) : (
          <DiffMode firstArt={firstArt!} lastArt={lastArt!} />
        )}
      </div>

      {editing && lastArt && (
        <ArtifactEditDialog
          artifact={lastArt}
          onCancel={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            onArtifactEdited?.();
          }}
        />
      )}
    </div>
  );
}

function RenderMode({
  firstArt,
  lastArt,
  stepArts,
}: {
  firstArt: Artifact | null;
  lastArt: Artifact | null;
  stepArts: Artifact[];
}) {
  // 至少要有一边有内容才渲染两栏；都没就退化到展示 stepArts 第一条
  const left = firstArt ?? lastArt ?? stepArts[0] ?? null;
  const right = lastArt ?? firstArt ?? stepArts[0] ?? null;

  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <section>
        <div className="mb-1 text-sm font-medium">首次输出</div>
        {left ? (
          <ArtifactViewer artifact={left} compact />
        ) : (
          <div className="rounded border border-dashed border-slate-300 p-4 text-center text-sm text-slate-400">
            无
          </div>
        )}
      </section>
      <section>
        <div className="mb-1 text-sm font-medium">上次输出</div>
        {right ? (
          <ArtifactViewer artifact={right} compact />
        ) : (
          <div className="rounded border border-dashed border-slate-300 p-4 text-center text-sm text-slate-400">
            无
          </div>
        )}
      </section>
    </div>
  );
}

function DiffMode({
  firstArt,
  lastArt,
}: {
  firstArt: Artifact;
  lastArt: Artifact;
}) {
  const [oldText, setOldText] = useState<string | null>(null);
  const [newText, setNewText] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // 只在两边 id 变化时重 fetch；同一对的对象引用变了不重新拉
  const fid = firstArt.id;
  const lid = lastArt.id;
  const fkey = firstArt.key;
  const lkey = lastArt.key;
  const fct = firstArt.content_type ?? null;
  const lct = lastArt.content_type ?? null;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    setOldText(null);
    setNewText(null);

    const fetchAndPrep = async (id: string, k: string, ct: string | null) => {
      const r = await fetch(artifactContentUrl(id));
      if (!r.ok) throw new Error(`${r.status}`);
      const raw = await r.text();
      // JSON 先 pretty-print 让 diff 能按字段比
      if (kind(ct, k) === "json") {
        try {
          return JSON.stringify(JSON.parse(raw), null, 2);
        } catch {
          return raw;
        }
      }
      return raw;
    };

    Promise.all([fetchAndPrep(fid, fkey, fct), fetchAndPrep(lid, lkey, lct)])
      .then(([o, n]) => {
        if (cancelled) return;
        setOldText(o);
        setNewText(n);
      })
      .catch((e) => {
        if (cancelled) return;
        setErr(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [fid, lid, fkey, lkey, fct, lct]);

  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <JuicerSpinner size={20} label="加载中…" />
      </div>
    );
  }
  if (err) {
    return (
      <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
        加载失败：{err}
      </div>
    );
  }
  if (oldText === null || newText === null) return null;

  if (oldText === newText) {
    return (
      <div className="space-y-2">
        <div className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          ✓ 首次输出和上次输出内容相同（还没改过）
        </div>
        <pre className="code max-h-96 overflow-auto whitespace-pre-wrap text-xs">
          {oldText}
        </pre>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded border border-slate-200">
      <ReactDiffViewer
        oldValue={oldText}
        newValue={newText}
        splitView
        leftTitle="首次输出"
        rightTitle="上次输出"
        useDarkTheme={false}
        styles={{
          contentText: { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12 },
          line: { wordBreak: "break-word" },
        }}
      />
    </div>
  );
}
