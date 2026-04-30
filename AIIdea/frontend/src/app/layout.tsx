import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Sidebar } from "@/components/sidebar";
import { Header } from "@/components/header";
import { TestHarness } from "@/components/test-harness";

const inter = Inter({
  variable: "--font-sans",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "AI 创意发现",
  description: "持续追踪全网信号，发现值得关注的产品创意",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="zh-CN"
      className={`${inter.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex bg-background" data-testid="app-root">
        <TestHarness />
        <Sidebar />
        <div className="flex-1 flex flex-col min-h-screen">
          <Header />
          <main
            className="flex-1 px-10 py-10 overflow-y-auto"
            data-testid="app-main"
          >
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
