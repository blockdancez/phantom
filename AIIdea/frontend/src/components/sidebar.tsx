"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const navItems: { href: string; label: string; testid?: string }[] = [
  { href: "/", label: "概览" },
  { href: "/sources", label: "数据" },
  { href: "/analysis", label: "创意 IDEA" },
  { href: "/products", label: "产品体验", testid: "sidebar-link-products" },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-[260px] shrink-0 border-r border-sidebar-border bg-sidebar min-h-screen flex flex-col">
      <div className="px-6 pt-7 pb-9">
        <div className="flex items-center gap-3">
          <div
            className="w-9 h-9 rounded-xl bg-primary flex items-center justify-center"
            style={{ boxShadow: "0 0 0 1px #b55435, 0 1px 2px rgba(181, 84, 53, 0.15)" }}
          >
            <span className="text-primary-foreground text-[13px] font-serif tracking-tight">AI</span>
          </div>
          <div>
            <h1 className="font-serif text-[17px] text-sidebar-accent-foreground leading-tight">
              创意发现
            </h1>
            <p className="text-[11px] text-muted-foreground mt-0.5 tracking-wider">
              产品信号阅览室
            </p>
          </div>
        </div>
      </div>
      <nav className="flex-1 px-4">
        <p className="text-[10px] font-medium text-muted-foreground tracking-[0.2em] px-3 mb-2">
          导航
        </p>
        <div className="space-y-0.5">
          {navItems.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                data-testid={item.testid}
                className={`flex items-center gap-2.5 px-3 py-[9px] rounded-lg text-[13.5px] font-medium tracking-tight transition-all ${
                  active
                    ? "bg-sidebar-accent text-sidebar-accent-foreground"
                    : "text-sidebar-foreground hover:bg-secondary/60 hover:text-sidebar-accent-foreground"
                }`}
                style={
                  active
                    ? { boxShadow: "0 0 0 1px var(--color-ring-warm)" }
                    : undefined
                }
              >
                <span
                  className={`w-1 h-1 rounded-full transition-colors ${
                    active ? "bg-primary" : "bg-transparent"
                  }`}
                />
                {item.label}
              </Link>
            );
          })}
        </div>
      </nav>
      <div className="px-6 py-5 border-t border-sidebar-border">
        <p className="text-[11px] text-muted-foreground font-serif italic">
          聚焦美国市场
        </p>
      </div>
    </aside>
  );
}
