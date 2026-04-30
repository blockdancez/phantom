"use client";

import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Artifact, artifactContentUrl, editArtifact } from "@/lib/api";
import { JuicerSpinner } from "@/components/juicer-spinner";

type Kind = "markdown" | "json" | "text" | "image" | "html" | "url" | "binary";

function kind(ct: string | null, key: string): Kind {
  const ext = key.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "url" || ct === "text/uri-list" || ct === "text/x-url") return "url";
  if (ext === "md" || ct === "text/markdown") return "markdown";
  if (ext === "json" || ct === "application/json") return "json";
  if (ext === "html" || ct === "text/html") return "html";
  if (["png", "jpg", "jpeg", "gif", "svg"].includes(ext) || (ct ?? "").startsWith("image/")) return "image";
  if ((ct ?? "").startsWith("text/") || ["txt", "py", "yml", "yaml", "log"].includes(ext)) return "text";
  return "binary";
}

function parseUriList(body: string): string[] {
  // RFC 2483: 每行一个 URI；以 # 开头的行为注释
  return body
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter((s) => s.length > 0 && !s.startsWith("#"));
}

export function ArtifactViewer({
  artifact,
  compact = false,
  editable = false,
  onEdited,
}: {
  artifact: Artifact | null;
  /** compact=true 时隐藏 step/key/size meta 行和"下载"按钮，仅展示内容 */
  compact?: boolean;
  /** 显示"编辑"按钮（仅文本类产物可用）；保存后调 onEdited 让父级刷新。 */
  editable?: boolean;
  onEdited?: () => void;
}) {
  const [body, setBody] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<string>("");
  const [comment, setComment] = useState<string>("");
  const [saving, setSaving] = useState(false);

  // 只在 artifact.id 变化时重新拉取内容；同一 artifact 的对象引用即便变化也不重 fetch，
  // 避免父级轮询导致弹窗内容反复 loading 闪烁。
  const id = artifact?.id;
  const ct = artifact?.content_type ?? null;
  const key = artifact?.key ?? "";
  useEffect(() => {
    if (!id) return;
    const k = kind(ct, key);
    if (k === "image" || k === "binary") {
      setBody(null);
      return;
    }
    setLoading(true);
    setErr(null);
    setBody(null);
    fetch(artifactContentUrl(id))
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(`${r.status}`))))
      .then(setBody)
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [id, ct, key]);

  if (!artifact)
    return (
      <div className="flex h-64 items-center justify-center text-sm text-slate-400">
        请选择一个产物查看
      </div>
    );

  const k = kind(artifact.content_type, artifact.key);
  const url = artifactContentUrl(artifact.id);
  const canEdit =
    editable && (k === "markdown" || k === "text" || k === "json" || k === "url" || k === "html");

  async function saveEdit() {
    if (!artifact) return;
    setSaving(true);
    setErr(null);
    try {
      await editArtifact(artifact.id, { content: draft, comment: comment.trim() || undefined });
      setBody(draft);
      setEditing(false);
      setComment("");
      onEdited?.();
    } catch (e: any) {
      setErr(e?.message ?? String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-3">
      {!compact && (
        <div className="flex items-center justify-between text-xs text-slate-500">
          <div className="font-mono">
            {artifact.step} / {artifact.key} · {artifact.size_bytes}B
            {artifact.content_type && <> · {artifact.content_type}</>}
          </div>
          <div className="flex items-center gap-1">
            {canEdit && !editing && (
              <button
                className="btn px-2 py-0.5 text-xs"
                onClick={() => {
                  setDraft(body ?? "");
                  setEditing(true);
                }}
                disabled={loading || body === null}
              >
                编辑
              </button>
            )}
            <a className="btn" href={url} target="_blank" rel="noreferrer">
              下载
            </a>
          </div>
        </div>
      )}

      {editing && (
        <div className="space-y-2 rounded border border-amber-200 bg-amber-50 p-3">
          <div className="text-xs text-amber-800">
            正在编辑 <span className="font-mono">{artifact.step} / {artifact.key}</span>
            ——保存后会写入 DB，并在历史里记一条 artifact.edited 事件。
          </div>
          <textarea
            className="h-64 w-full rounded border border-slate-300 bg-white p-2 font-mono text-xs"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <input
            type="text"
            className="w-full rounded border border-slate-300 bg-white px-2 py-1 text-sm"
            placeholder="备注（可选，例如：修正错别字）"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <button
              className="btn"
              onClick={() => {
                setEditing(false);
                setComment("");
              }}
              disabled={saving}
            >
              取消
            </button>
            <button className="btn btn-primary" onClick={saveEdit} disabled={saving}>
              {saving ? "保存中…" : "保存"}
            </button>
          </div>
        </div>
      )}

      {loading && <JuicerSpinner size={18} label="加载中…" />}
      {err && <div className="rounded bg-rose-50 px-3 py-2 text-sm text-rose-700">{err}</div>}

      {k === "image" && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt={artifact.key} className="max-h-[600px] rounded border" />
      )}
      {k === "markdown" && body && (
        <article className="prose prose-slate max-w-none rounded-md border border-slate-200 bg-white p-4 text-sm">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{body}</ReactMarkdown>
        </article>
      )}
      {k === "json" && body && (
        <pre className="code">{(() => {
          try {
            return JSON.stringify(JSON.parse(body), null, 2);
          } catch {
            return body;
          }
        })()}</pre>
      )}
      {k === "text" && body && <pre className="code">{body}</pre>}
      {k === "html" && body && (
        <iframe className="h-[500px] w-full rounded border bg-white" srcDoc={body} sandbox="" />
      )}
      {k === "url" && body && (
        <div className="space-y-2 rounded-md border border-slate-200 bg-white p-4">
          {parseUriList(body).map((u) => (
            <div key={u} className="flex items-center gap-2 text-sm">
              <span className="text-slate-400">🔗</span>
              <a
                href={u}
                target="_blank"
                rel="noreferrer"
                className="break-all text-brand-700 hover:underline"
              >
                {u}
              </a>
            </div>
          ))}
          {parseUriList(body).length === 0 && (
            <div className="text-sm text-slate-400">URL 列表为空</div>
          )}
        </div>
      )}
      {k === "binary" && (
        <div className="rounded border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm text-slate-500">
          二进制文件不支持在线预览，请点击右上角下载
        </div>
      )}
    </div>
  );
}
