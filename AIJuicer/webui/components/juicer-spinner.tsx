// 榨汁动画：任何"进行中"状态都用它，强化 AI 榨汁机的品牌一致性。
// 纯 SVG + CSS keyframe（定义在 globals.css），server/client component 都可用。

type Props = {
  size?: number;
  label?: string;
  className?: string;
};

export function JuicerSpinner({ size = 20, label, className = "" }: Props) {
  const h = Math.round((size * 4) / 3);
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <svg
        width={size}
        height={h}
        viewBox="0 0 48 64"
        aria-label="榨汁中"
        role="img"
        style={{ flexShrink: 0 }}
      >
        {/* 橙子：被挤压的动画 */}
        <g
          style={{
            transformBox: "fill-box",
            transformOrigin: "center",
            animation: "juicer-squeeze 0.9s ease-in-out infinite",
          }}
        >
          <circle cx="24" cy="12" r="8" fill="#fb923c" />
          <path
            d="M 24 4 Q 25 6 26 4"
            stroke="#65a30d"
            strokeWidth="1.5"
            fill="none"
            strokeLinecap="round"
          />
          <circle cx="21" cy="10" r="1.2" fill="#fdba74" opacity="0.7" />
        </g>
        {/* 榨汁机漏斗 */}
        <path
          d="M 10 22 L 38 22 L 32 32 L 16 32 Z"
          fill="#facc15"
          stroke="#ca8a04"
          strokeWidth="1"
          strokeLinejoin="round"
        />
        <rect x="21" y="32" width="6" height="3" fill="#ca8a04" />
        {/* 果汁滴落 */}
        <ellipse
          cx="22"
          cy="40"
          rx="1.5"
          ry="2"
          fill="#fbbf24"
          style={{
            transformBox: "fill-box",
            transformOrigin: "center",
            animation: "juicer-drop 0.9s linear infinite",
          }}
        />
        <ellipse
          cx="26"
          cy="40"
          rx="1.5"
          ry="2"
          fill="#fbbf24"
          style={{
            transformBox: "fill-box",
            transformOrigin: "center",
            animation: "juicer-drop 0.9s linear infinite 0.45s",
          }}
        />
        {/* 杯子 */}
        <path
          d="M 13 44 L 35 44 L 32 60 L 16 60 Z"
          fill="none"
          stroke="#64748b"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        {/* 杯中液面（上下轻微起伏） */}
        <path
          d="M 15 50 L 33 50 L 31 58 L 17 58 Z"
          fill="#fbbf24"
          style={{
            transformBox: "fill-box",
            transformOrigin: "center bottom",
            animation: "juicer-fill 0.9s ease-in-out infinite",
          }}
        />
        {/* 闪光小点 */}
        <circle
          cx="36"
          cy="14"
          r="1"
          fill="#fde047"
          style={{ animation: "juicer-sparkle 1.2s ease-in-out infinite" }}
        />
        <circle
          cx="10"
          cy="18"
          r="0.8"
          fill="#fde047"
          style={{ animation: "juicer-sparkle 1.2s ease-in-out infinite 0.6s" }}
        />
      </svg>
      {label && <span className="text-xs text-slate-500">{label}</span>}
    </span>
  );
}
