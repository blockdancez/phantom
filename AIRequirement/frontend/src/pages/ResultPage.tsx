import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getIdea, getDocumentForIdea } from "../api";
import type { Idea, Document } from "../api";
import StatusBadge from "../components/StatusBadge";
import DocumentView from "../components/DocumentView";

export default function ResultPage() {
  const { ideaId } = useParams<{ ideaId: string }>();
  const [idea, setIdea] = useState<Idea | null>(null);
  const [document, setDocument] = useState<Document | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!ideaId) return;

    const poll = async () => {
      try {
        const ideaData = await getIdea(ideaId);
        setIdea(ideaData);

        if (ideaData.status === "completed") {
          const doc = await getDocumentForIdea(ideaId);
          setDocument(doc);
          return true;
        }
        if (ideaData.status === "failed") {
          setError("生成失败，请重试");
          return true;
        }
        return false;
      } catch {
        setError("加载失败");
        return true;
      }
    };

    let timer: ReturnType<typeof setInterval>;

    poll().then((done) => {
      if (!done) {
        timer = setInterval(async () => {
          const done = await poll();
          if (done) clearInterval(timer);
        }, 3000);
      }
    });

    return () => clearInterval(timer);
  }, [ideaId]);

  if (error) {
    return (
      <div className="text-center py-16">
        <p className="text-[#8b3a3a] mb-4">{error}</p>
        <Link
          to="/"
          className="text-terracotta hover:text-terracotta-hover font-medium text-sm transition-colors"
        >
          返回首页
        </Link>
      </div>
    );
  }

  if (!idea) {
    return (
      <div className="text-center py-16 text-stone">加载中...</div>
    );
  }

  if (!document) {
    return (
      <div className="max-w-md mx-auto text-center py-16">
        <div className="mb-5">
          <StatusBadge status={idea.status} />
        </div>
        <h2 className="font-serif text-xl text-near-black mb-3">
          正在生成需求文档
        </h2>
        <p className="text-olive text-sm leading-relaxed mb-6">
          "{idea.content}"
        </p>
        <div className="flex justify-center mb-5">
          <div className="w-8 h-8 rounded-full border-2 border-border-warm border-t-terracotta animate-spin" />
        </div>
        <p className="text-xs text-stone">
          {idea.status === "researching" && "正在调研竞品..."}
          {idea.status === "writing" && "正在撰写文档..."}
          {idea.status === "pending" && "排队中..."}
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="mb-6 flex items-center gap-4">
        <Link
          to="/"
          className="text-stone hover:text-terracotta text-sm transition-colors"
        >
          ← 新建
        </Link>
        <Link
          to="/history"
          className="text-stone hover:text-terracotta text-sm transition-colors"
        >
          历史
        </Link>
      </div>
      <DocumentView title={document.title} content={document.content} />
    </div>
  );
}
