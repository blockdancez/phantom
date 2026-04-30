import { useState } from "react";

interface Props {
  onSubmit: (content: string) => void;
  loading: boolean;
}

export default function IdeaForm({ onSubmit, loading }: Props) {
  const [content, setContent] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (content.trim()) {
      onSubmit(content.trim());
      setContent("");
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <label
          htmlFor="idea"
          className="block text-sm font-medium text-charcoal mb-2"
        >
          描述你的产品 Idea
        </label>
        <textarea
          id="idea"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="例如：一个帮助远程团队更高效进行异步沟通的协作工具，支持语音留言、智能摘要和任务追踪..."
          rows={6}
          maxLength={5000}
          className="w-full rounded-xl border border-border-warm bg-ivory px-4 py-3 text-near-black placeholder-warm-silver focus:border-terracotta focus:ring-1 focus:ring-terracotta/30 resize-none transition-colors outline-none leading-relaxed"
          disabled={loading}
        />
        <p className="text-xs text-stone mt-1.5 text-right">
          {content.length} / 5000
        </p>
      </div>
      <button
        type="submit"
        disabled={!content.trim() || loading}
        className="w-full rounded-xl bg-terracotta px-5 py-3.5 text-white font-medium hover:bg-terracotta-hover disabled:opacity-40 disabled:cursor-not-allowed transition-all shadow-[0_0_0_1px_rgba(201,100,66,0.3)] hover:shadow-[0_0_0_1px_rgba(201,100,66,0.5)]"
      >
        {loading ? "提交中..." : "生成产品需求文档"}
      </button>
    </form>
  );
}
