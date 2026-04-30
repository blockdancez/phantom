import Link from "next/link";
import { WorkflowListResponse, listWorkflows } from "@/lib/api";
import { Pagination } from "@/components/pagination";
import { WorkflowFilters } from "@/components/workflow-filters";
import { WorkflowRow } from "@/components/workflow-row";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 20;

export default async function WorkflowsPage({
  searchParams,
}: {
  searchParams: { q?: string; status_group?: string; page?: string };
}) {
  const page = Math.max(1, parseInt(searchParams.page ?? "1", 10) || 1);
  const q = searchParams.q ?? "";
  const statusGroup = searchParams.status_group ?? "";

  let data: WorkflowListResponse = {
    items: [],
    total: 0,
    page,
    page_size: PAGE_SIZE,
  };
  let error: string | null = null;
  try {
    data = await listWorkflows({
      q: q || undefined,
      status_group: statusGroup || undefined,
      page,
      page_size: PAGE_SIZE,
    });
  } catch (e: any) {
    error = e.message ?? String(e);
  }

  const baseQuery = new URLSearchParams();
  if (q) baseQuery.set("q", q);
  if (statusGroup) baseQuery.set("status_group", statusGroup);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold">工作流</h1>
        <Link href="/workflows/new" className="btn btn-primary">
          + 新建工作流
        </Link>
      </div>

      <WorkflowFilters />

      {error && (
        <div className="card border-rose-200 bg-rose-50 p-3 text-sm text-rose-800">
          加载工作流失败：{error}
        </div>
      )}

      <div className="card overflow-hidden">
        <table className="w-full text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-left text-xs uppercase tracking-wider text-slate-500">
            <tr>
              <th className="px-4 py-2">项目标题</th>
              <th className="px-4 py-2">状态</th>
              <th className="px-4 py-2">当前步骤</th>
              <th className="px-4 py-2">创建时间</th>
              <th className="px-4 py-2 text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {data.items.length === 0 && !error ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-slate-400">
                  {q || statusGroup
                    ? "没有匹配的工作流；试试调整筛选条件"
                    : "暂无工作流"}
                </td>
              </tr>
            ) : (
              data.items.map((w) => <WorkflowRow key={w.id} w={w} />)
            )}
          </tbody>
        </table>
        <div className="border-t border-slate-200">
          <Pagination
            page={data.page}
            pageSize={data.page_size}
            total={data.total}
            baseQuery={baseQuery}
          />
        </div>
      </div>
    </div>
  );
}
