interface ScoreIndicatorProps {
  score: number;
}

export function ScoreIndicator({ score }: ScoreIndicatorProps) {
  // Warm semantic palette: olive / honey / crimson — no cool greens or reds
  const style =
    score >= 8
      ? {
          color: "#5b6b43",
          background: "rgba(122, 140, 92, 0.12)",
          boxShadow: "0 0 0 1px rgba(122, 140, 92, 0.35)",
        }
      : score >= 6
        ? {
            color: "#8a6a20",
            background: "rgba(212, 160, 74, 0.14)",
            boxShadow: "0 0 0 1px rgba(212, 160, 74, 0.4)",
          }
        : {
            color: "#8a2525",
            background: "rgba(181, 51, 51, 0.1)",
            boxShadow: "0 0 0 1px rgba(181, 51, 51, 0.3)",
          };

  return (
    <span
      className="inline-flex items-center px-2.5 py-0.5 rounded-md text-[13px] font-semibold tracking-tight tabular-nums"
      style={style}
    >
      {score.toFixed(1)}
    </span>
  );
}
