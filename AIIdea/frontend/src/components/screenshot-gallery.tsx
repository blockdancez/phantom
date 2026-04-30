"use client";

import Image from "next/image";
import { useState } from "react";
import type { ScreenshotEntry } from "@/lib/types";

const STATIC_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:53839";

export function ScreenshotGallery({ shots }: { shots: ScreenshotEntry[] }) {
  const [active, setActive] = useState<ScreenshotEntry | null>(null);
  if (!shots || shots.length === 0) {
    return (
      <p className="text-sm text-muted-foreground" data-testid="product-detail-screenshots-empty">
        本次体验没有截图
      </p>
    );
  }
  return (
    <div data-testid="product-detail-screenshots">
      <div className="grid grid-cols-3 gap-3">
        {shots.map((s) => (
          <button
            key={s.path}
            onClick={() => setActive(s)}
            className="relative aspect-video overflow-hidden rounded-md border hover:ring-2 hover:ring-primary/40"
            data-testid={`product-detail-screenshot-${s.name}`}
          >
            <Image
              src={`${STATIC_BASE}/static/codex/${s.path}`}
              alt={s.name}
              fill
              sizes="(max-width: 768px) 33vw, 200px"
              className="object-cover"
              unoptimized
            />
            <span className="absolute bottom-0 left-0 right-0 bg-black/50 text-white text-[11px] px-1 py-0.5 truncate">
              {s.name}
            </span>
          </button>
        ))}
      </div>
      {active && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-8"
          onClick={() => setActive(null)}
        >
          <Image
            src={`${STATIC_BASE}/static/screenshots/${active.path}`}
            alt={active.name}
            width={1280}
            height={720}
            className="max-h-full max-w-full object-contain"
            unoptimized
          />
        </div>
      )}
    </div>
  );
}
