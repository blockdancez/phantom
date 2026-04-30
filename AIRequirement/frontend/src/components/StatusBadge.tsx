const STATUS_CONFIG: Record<string, { label: string; className: string }> = {
  pending: { label: "等待中", className: "bg-sand text-stone" },
  researching: { label: "调研中", className: "bg-[#e8eedc] text-[#5a6b3a]" },
  writing: { label: "撰写中", className: "bg-[#f5e6dc] text-terracotta" },
  completed: { label: "已完成", className: "bg-[#dce8dc] text-[#3a6b3a]" },
  failed: { label: "失败", className: "bg-[#f5dcdc] text-[#8b3a3a]" },
};

export default function StatusBadge({ status }: { status: string }) {
  const config = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${config.className}`}
    >
      {config.label}
    </span>
  );
}
