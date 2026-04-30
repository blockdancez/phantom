import { useEffect, useState } from "react";
import { listIdeas } from "../api";
import type { Idea } from "../api";
import DocumentList from "../components/DocumentList";

export default function HistoryPage() {
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listIdeas()
      .then((data) => setIdeas(data.ideas))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="text-center py-16 text-stone">加载中...</div>
    );
  }

  return (
    <div>
      <h1 className="font-serif text-2xl text-near-black mb-6">历史记录</h1>
      <DocumentList ideas={ideas} />
    </div>
  );
}
