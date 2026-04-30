"use client";

import ReactFlow, {
  Background,
  Controls,
  Edge,
  Handle,
  Node,
  Position,
} from "reactflow";
import "reactflow/dist/style.css";
import { STEPS, stepLabel, stepState } from "@/lib/api";
import { JuicerSpinner } from "@/components/juicer-spinner";

type StepState = ReturnType<typeof stepState>;

const STATE_STYLE: Record<StepState, { bg: string; border: string; text: string; label: string }> = {
  pending: { bg: "#f8fafc", border: "#e2e8f0", text: "#64748b", label: "待执行" },
  running: { bg: "#eef2ff", border: "#6366f1", text: "#4338ca", label: "执行中" },
  awaiting: { bg: "#eff6ff", border: "#3b82f6", text: "#1d4ed8", label: "待审批" },
  done: { bg: "#ecfdf5", border: "#10b981", text: "#047857", label: "已完成" },
  failed: { bg: "#fef2f2", border: "#ef4444", text: "#b91c1c", label: "失败" },
  completed: { bg: "#ecfdf5", border: "#10b981", text: "#047857", label: "已完成" },
};

function StepNode({ data }: { data: { step: string; state: StepState; index: number } }) {
  const s = STATE_STYLE[data.state];
  return (
    <div
      className="rounded-lg border-2 px-4 py-2 shadow-sm"
      style={{ background: s.bg, borderColor: s.border, minWidth: 140, height: 76 }}
    >
      <Handle type="target" position={Position.Left} style={{ opacity: 0 }} />
      <div className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: s.text }}>
        第 {data.index + 1} 步
      </div>
      <div className="font-medium text-slate-900">{stepLabel(data.step)}</div>
      <div
        className="mt-0.5 flex items-center gap-1 text-[11px] leading-4"
        style={{ color: s.text, height: 16 }}
      >
        {data.state === "running" ? (
          <>
            <JuicerSpinner size={14} />
            <span>榨汁中…</span>
          </>
        ) : (
          <span>{s.label}</span>
        )}
      </div>
      <Handle type="source" position={Position.Right} style={{ opacity: 0 }} />
    </div>
  );
}

const nodeTypes = { step: StepNode };

export default function Dag({
  status,
  failedStep,
}: {
  status: string;
  failedStep: string | null;
}) {
  const nodes: Node[] = STEPS.map((step, i) => ({
    id: step,
    type: "step",
    position: { x: i * 180, y: 0 },
    data: { step, state: stepState(step, status, failedStep), index: i },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
  }));
  const edges: Edge[] = STEPS.slice(0, -1).map((step, i) => ({
    id: `${step}->${STEPS[i + 1]}`,
    source: step,
    target: STEPS[i + 1],
    type: "smoothstep",
    animated: false,
  }));
  return (
    <div style={{ height: 180 }} className="card overflow-hidden">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.3 }}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={16} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
