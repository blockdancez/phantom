export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8000";

export type Workflow = {
  id: string;
  name: string;
  /** 项目 slug：小写英文 + 短横线，全局唯一。后续做仓库 / 数据库 / 文件夹命名用。 */
  project_name: string | null;
  status: string;
  input: Record<string, unknown>;
  approval_policy: Record<string, string>;
  current_step: string | null;
  failed_step: string | null;
  artifact_root: string;
  created_at: string;
  updated_at: string;
};

export type Artifact = {
  id: string;
  workflow_id: string;
  step: string;
  key: string;
  attempt: number;
  path: string | null;
  size_bytes: number;
  content_type: string | null;
  sha256: string | null;
  created_at: string;
};

export type AgentInfo = {
  id: string;
  name: string;
  step: string;
  status: string;
  last_seen_at: string;
  host?: string | null;
  port?: number | null;
  pid?: number | null;
  hostname?: string | null;
};

async function handle<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
  return (await r.json()) as T;
}

export type WorkflowListResponse = {
  items: Workflow[];
  total: number;
  page: number;
  page_size: number;
};

export type WorkflowListOpts = {
  q?: string;
  status?: string;
  status_group?: string;
  page?: number;
  page_size?: number;
};

export async function listWorkflows(
  opts: WorkflowListOpts = {},
): Promise<WorkflowListResponse> {
  const params = new URLSearchParams();
  if (opts.q) params.set("q", opts.q);
  if (opts.status) params.set("status", opts.status);
  if (opts.status_group) params.set("status_group", opts.status_group);
  params.set("page", String(opts.page ?? 1));
  params.set("page_size", String(opts.page_size ?? 20));
  return handle(
    await fetch(`${API_BASE}/api/workflows?${params.toString()}`, { cache: "no-store" }),
  );
}

export const STATUS_GROUPS: Array<{ value: string; label: string }> = [
  { value: "", label: "全部" },
  { value: "running", label: "进行中" },
  { value: "awaiting", label: "等待审批" },
  { value: "manual", label: "需人工介入" },
  { value: "completed", label: "已完成" },
  { value: "aborted", label: "已中止" },
  { value: "active", label: "未结束" },
];

export async function getWorkflow(id: string): Promise<Workflow> {
  return handle(await fetch(`${API_BASE}/api/workflows/${id}`, { cache: "no-store" }));
}

export async function createWorkflow(body: {
  name: string;
  /** 项目 slug：小写英文 + 短横线，撞名时 scheduler 自动加 4 位随机后缀。 */
  project_name: string;
  input: Record<string, unknown>;
  approval_policy: Record<string, string>;
}): Promise<Workflow> {
  return handle(
    await fetch(`${API_BASE}/api/workflows`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function submitApproval(
  wfId: string,
  body: {
    decision: string;
    step?: string;
    comment?: string;
    modified_input?: Record<string, unknown>;
  },
) {
  return handle(
    await fetch(`${API_BASE}/api/workflows/${wfId}/approvals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export async function listArtifacts(wfId: string): Promise<Artifact[]> {
  return handle(
    await fetch(`${API_BASE}/api/workflows/${wfId}/artifacts`, { cache: "no-store" }),
  );
}

export async function listAgents(): Promise<AgentInfo[]> {
  return handle(await fetch(`${API_BASE}/api/agents`, { cache: "no-store" }));
}

export async function deleteWorkflow(id: string): Promise<void> {
  const r = await fetch(`${API_BASE}/api/workflows/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204)
    throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
}

export type SystemStatus = {
  redis: {
    url: string;
    ping: boolean;
    ping_ms: number;
    version?: string;
    mode?: string;
    uptime_sec?: number;
    used_memory_human?: string;
    connected_clients?: number;
    total_commands_processed?: number;
  };
  steps: Array<{
    step: string;
    stream: string;
    group: string;
    stream_length: number;
    pending: number;
    consumers: Array<{ name: string; pending: number; idle_ms: number }>;
    agents_online: number;
  }>;
};

export async function getSystemStatus(): Promise<SystemStatus> {
  return handle(await fetch(`${API_BASE}/api/system/status`, { cache: "no-store" }));
}

export type DashboardSummary = {
  pending: Workflow[];
  totals: {
    running: number;
    awaiting: number;
    manual: number;
    completed: number;
    aborted: number;
    total: number;
  };
  grid: Record<string, { running: number; awaiting: number; failed: number; done: number }>;
  status_counts: Record<string, number>;
};

export async function getDashboardSummary(): Promise<DashboardSummary> {
  return handle(await fetch(`${API_BASE}/api/dashboard/summary`, { cache: "no-store" }));
}

export function artifactContentUrl(artId: string): string {
  return `${API_BASE}/api/artifacts/${artId}/content`;
}

export async function editArtifact(
  artId: string,
  body: { content: string; comment?: string },
): Promise<Artifact> {
  return handle(
    await fetch(`${API_BASE}/api/artifacts/${artId}/content`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export type HistoryEntry =
  | {
      kind: "approval";
      decision: string;
      step: string;
      comment: string | null;
      payload: Record<string, unknown> | null;
      created_at: string;
    }
  | {
      kind: "artifact_edited";
      step: string | null;
      key: string | null;
      comment: string | null;
      payload: Record<string, unknown> | null;
      request_id: string | null;
      created_at: string;
    };

export async function listWorkflowHistory(wfId: string): Promise<HistoryEntry[]> {
  return handle(
    await fetch(`${API_BASE}/api/workflows/${wfId}/history`, { cache: "no-store" }),
  );
}

export function workflowEventsUrl(wfId: string): string {
  return `${API_BASE}/api/workflows/${wfId}/events`;
}

export const STEPS = ["idea", "requirement", "plan", "design", "devtest", "deploy"];

// —— 中文映射 ——
export const STEP_LABEL: Record<string, string> = {
  idea: "想法",
  requirement: "需求",
  plan: "计划",
  design: "设计",
  devtest: "开发测试",
  deploy: "部署",
};

export function stepLabel(step: string | null | undefined): string {
  if (!step) return "-";
  return STEP_LABEL[step] ?? step;
}

const PHASE_LABEL: Record<string, string> = {
  RUNNING: "进行中",
  DONE: "完成",
};

export function statusLabel(status: string): string {
  if (status === "CREATED") return "已创建";
  if (status === "COMPLETED") return "已完成";
  if (status === "ABORTED") return "已中止";
  if (status === "AWAITING_MANUAL_ACTION") return "需人工介入";
  if (status.startsWith("AWAITING_APPROVAL_")) {
    // 后端状态码 AWAITING_APPROVAL_<NEXT> 实际是"审批刚完成的上一步产物"，
    // 通过则进入 NEXT。展示时用上一步的名字更贴近用户心智。
    const next = status.replace("AWAITING_APPROVAL_", "").toLowerCase();
    const prev = prevStep(next) ?? next;
    return `等待审批·${stepLabel(prev)}`;
  }
  const m = status.match(/^([A-Z]+)_(RUNNING|DONE)$/);
  if (m) {
    const step = m[1].toLowerCase();
    return `${stepLabel(step)}·${PHASE_LABEL[m[2]] ?? m[2]}`;
  }
  return status;
}

// 前一步（用于"重新执行"按钮：从等待审批下一步回退到再跑上一步）
export function prevStep(currentStep: string | null | undefined): string | null {
  if (!currentStep) return null;
  const idx = STEPS.indexOf(currentStep);
  if (idx <= 0) return null;
  return STEPS[idx - 1];
}

export function stepState(
  step: string,
  status: string,
  failedStep: string | null,
): "pending" | "running" | "awaiting" | "done" | "failed" | "completed" {
  const up = step.toUpperCase();
  if (status === "COMPLETED") return "completed";
  if (status === "ABORTED") return failedStep === step ? "failed" : "pending";
  if (status === "AWAITING_MANUAL_ACTION") return failedStep === step ? "failed" : "pending";
  if (status === `${up}_RUNNING`) return "running";
  if (status === `${up}_DONE`) return "done";
  // AWAITING_APPROVAL_<NEXT> ：实际等审批的是 prev，next 还没启动。
  if (status.startsWith("AWAITING_APPROVAL_")) {
    const next = status.replace("AWAITING_APPROVAL_", "").toLowerCase();
    const prev = prevStep(next);
    if (prev && step === prev) return "awaiting";
    if (step === next) return "pending";
    const idx = STEPS.indexOf(step);
    const prevIdx = prev ? STEPS.indexOf(prev) : -1;
    return idx < prevIdx ? "done" : "pending";
  }
  // Steps before current
  const idx = STEPS.indexOf(step);
  const currentStep = inferStepFromStatus(status);
  const curIdx = currentStep ? STEPS.indexOf(currentStep) : -1;
  if (curIdx > idx) return "done";
  return "pending";
}

function inferStepFromStatus(status: string): string | null {
  for (const s of STEPS) {
    const up = s.toUpperCase();
    if (
      status === `${up}_RUNNING` ||
      status === `${up}_DONE` ||
      status === `AWAITING_APPROVAL_${up}`
    )
      return s;
  }
  return null;
}
