import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "AI 榨汁机",
  description: "AI 榨汁机 · 端到端软件交付流水线调度平台",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh">
      <body>
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
            <Link href="/" className="font-semibold">
              🧃 AI 榨汁机
            </Link>
            <nav className="flex gap-4 text-sm text-slate-600">
              <Link href="/workflows" className="hover:text-slate-900">
                工作流
              </Link>
              <Link href="/workflows/new" className="hover:text-slate-900">
                新建
              </Link>
              <Link href="/agents" className="hover:text-slate-900">
                Agent
              </Link>
              <Link href="/system/health" className="hover:text-slate-900">
                系统状态
              </Link>
            </nav>
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
