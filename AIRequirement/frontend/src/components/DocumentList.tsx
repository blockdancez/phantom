import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import type { Idea } from "../api";
import { regenerateIdea } from "../api";
import StatusBadge from "./StatusBadge";
import RegenerateModal from "./RegenerateModal";

interface Props {
  ideas: Idea[];
}

export default function DocumentList({ ideas }: Props) {
  const navigate = useNavigate();
  const [target, setTarget] = useState<Idea | null>(null);

  if (ideas.length === 0) {
    return (
      <div className="text-center py-16">
        <p className="text-stone mb-3">还没有生成过需求文档</p>
        <Link
          to="/"
          className="text-terracotta hover:text-terracotta-hover font-medium text-sm transition-colors"
        >
          去创建一个 →
        </Link>
      </div>
    );
  }

  const openModal = (e: React.MouseEvent, idea: Idea) => {
    e.preventDefault();
    e.stopPropagation();
    setTarget(idea);
  };

  const handleConfirm = async (instruction: string | undefined) => {
    if (!target) return;
    await regenerateIdea(target.id, instruction);
    const id = target.id;
    setTarget(null);
    navigate(`/result/${id}`);
  };

  return (
    <>
      <div className="space-y-3">
        {ideas.map((idea) => {
          const running = idea.status === "researching" || idea.status === "writing";
          return (
            <Link
              key={idea.id}
              to={`/result/${idea.id}`}
              className="block bg-ivory rounded-xl shadow-[0_0_0_1px_var(--color-border-cream)] p-5 hover:shadow-[0_0_0_1px_var(--color-border-warm)] transition-all"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <p className="text-near-black font-medium truncate leading-relaxed">
                    {idea.content}
                  </p>
                  <p className="text-xs text-stone mt-1.5">
                    {new Date(idea.created_at).toLocaleString("zh-CN")}
                  </p>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <StatusBadge status={idea.status} />
                  <button
                    type="button"
                    onClick={(e) => openModal(e, idea)}
                    disabled={running}
                    className="text-xs px-3 py-1.5 rounded-md border border-[var(--color-border-warm)] text-terracotta hover:bg-terracotta hover:text-ivory hover:border-terracotta disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-terracotta transition-colors"
                    title={running ? "任务进行中" : "用相同 idea（可附重跑指令）重新生成"}
                  >
                    重新生成
                  </button>
                </div>
              </div>
            </Link>
          );
        })}
      </div>

      {target && (
        <RegenerateModal
          ideaContent={target.content}
          onConfirm={handleConfirm}
          onClose={() => setTarget(null)}
        />
      )}
    </>
  );
}
