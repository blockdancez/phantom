"use client";

import { useEffect, useState } from "react";
import {
  Artifact,
  artifactContentUrl,
  editArtifact,
  stepLabel,
} from "@/lib/api";
import { JuicerSpinner } from "@/components/juicer-spinner";

type Props = {
  artifact: Artifact;
  onCancel: () => void;
  /** 保存成功后调用，父级一般用来刷新列表 / 对比面板。 */
  onSaved: () => void;
};

export function ArtifactEditDialog({ artifact, onCancel, onSaved }: Props) {
  const [draft, setDraft] = useState<string | null>(null);
  const [comment, setComment] = useState<string>("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // 拉当前产物字节预填进 textarea
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr(null);
    fetch(artifactContentUrl(artifact.id))
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`${r.status}`))))
      .then((t) => {
        if (!cancelled) setDraft(t);
      })
      .catch((e) => {
        if (!cancelled) setErr(String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [artifact.id]);

  // ESC 关闭
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  async function save() {
    if (draft === null) return;
    setSaving(true);
    setErr(null);
    try {
      await editArtifact(artifact.id, {
        content: draft,
        comment: comment.trim() || undefined,
      });
      onSaved();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      onClick={onCancel}
    >
      <div
        className="card flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
          <h2 className="text-base font-semibold">
            编辑产物 · <span className="text-brand-700">{stepLabel(artifact.step)}</span>
            <span className="ml-2 font-mono text-xs text-slate-400">{artifact.key}</span>
          </h2>
          <button className="btn text-sm" onClick={onCancel}>
            ✕
          </button>
        </div>

        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {loading && (
            <div className="flex h-48 items-center justify-center">
              <JuicerSpinner size={20} label="加载内容…" />
            </div>
          )}

          {!loading && draft !== null && (
            <>
              <textarea
                autoFocus
                rows={20}
                className="w-full rounded border border-slate-300 bg-white p-2 font-mono text-xs"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
              <input
                type="text"
                className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm"
                placeholder="备注（可选，例如：修正了开头的错别字）"
                value={comment}
                onChange={(e) => setComment(e.target.value)}
              />
              <div className="text-xs text-slate-400">
                保存后会调用 PUT /api/artifacts/{"{id}"}/content；同时在历史里记一条
                artifact.edited 事件。原始的 .first 快照不会变。
              </div>
            </>
          )}

          {err && (
            <div className="rounded border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">
              {err}
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 border-t border-slate-200 px-4 py-3">
          <button className="btn" onClick={onCancel} disabled={saving}>
            取消
          </button>
          <button
            className="btn btn-primary"
            onClick={save}
            disabled={saving || loading || draft === null}
          >
            {saving ? "保存中…" : "保存"}
          </button>
        </div>
      </div>
    </div>
  );
}
