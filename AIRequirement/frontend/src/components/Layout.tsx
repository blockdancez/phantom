import { Link, Outlet, useLocation } from "react-router-dom";

export default function Layout() {
  const location = useLocation();

  const navLink = (to: string, label: string) => {
    const active = location.pathname === to;
    return (
      <Link
        to={to}
        className={`text-sm font-medium transition-colors ${
          active
            ? "text-terracotta"
            : "text-stone hover:text-near-black"
        }`}
      >
        {label}
      </Link>
    );
  };

  return (
    <div className="min-h-screen bg-parchment">
      <nav className="bg-ivory/80 backdrop-blur-sm border-b border-border-cream sticky top-0 z-10">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-terracotta flex items-center justify-center">
              <span className="text-white text-xs font-semibold">P</span>
            </div>
            <span className="font-serif text-lg text-near-black">PRD Agent</span>
          </Link>
          <div className="flex gap-6">
            {navLink("/", "新建")}
            {navLink("/history", "历史")}
          </div>
        </div>
      </nav>
      <main className="max-w-4xl mx-auto px-6 py-10">
        <Outlet />
      </main>
    </div>
  );
}
