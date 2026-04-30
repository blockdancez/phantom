interface TagBadgeProps {
  tag: string;
}

export function TagBadge({ tag }: TagBadgeProps) {
  return (
    <span
      className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-medium tracking-tight text-muted-foreground bg-secondary/70"
      style={{ boxShadow: "0 0 0 1px var(--color-border-warm)" }}
    >
      {tag}
    </span>
  );
}
