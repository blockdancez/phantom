export function Header() {
  return (
    <header className="h-14 border-b border-border flex items-center px-8 bg-card/70 backdrop-blur-sm">
      <div className="flex items-center gap-2.5 text-[13px] text-muted-foreground">
        <span
          className="inline-block w-1.5 h-1.5 rounded-full animate-pulse"
          style={{ background: "var(--color-success)" }}
        />
        <span className="tracking-tight">系统运行中</span>
        <span className="text-border mx-2">·</span>
        <span className="font-serif italic text-[13px]">来自互联网的细声</span>
      </div>
    </header>
  );
}
