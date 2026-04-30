import { useState } from "react";
import { useNavigate } from "react-router-dom";
import IdeaForm from "../components/IdeaForm";
import { createIdea } from "../api";

export default function HomePage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleSubmit = async (content: string) => {
    setLoading(true);
    setError(null);
    try {
      const idea = await createIdea(content);
      navigate(`/result/${idea.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败，请重试");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto">
      <div className="text-center mb-10">
        <h1 className="font-serif text-3xl text-near-black mb-3">
          将 Idea 变为产品需求
        </h1>
        <p className="text-olive leading-relaxed">
          输入你的产品 Idea，AI 将自动调研竞品并生成完整的产品需求文档
        </p>
      </div>
      <div className="bg-ivory rounded-2xl shadow-[0_0_0_1px_var(--color-border-cream)] p-7">
        <IdeaForm onSubmit={handleSubmit} loading={loading} />
        {error && (
          <p className="mt-5 text-sm text-[#8b3a3a] bg-[#f5dcdc] rounded-xl p-3.5">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
