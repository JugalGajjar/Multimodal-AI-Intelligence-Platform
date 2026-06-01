"use client";

import { LayoutDashboard, Network, Sparkles } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { BrandMark } from "@/components/layout/brand-mark";

type NavItem = {
  href: string;
  label: string;
  Icon: typeof LayoutDashboard;
  match?: (pathname: string) => boolean;
};

const NAV: NavItem[] = [
  {
    href: "/dashboard",
    label: "Dashboard",
    Icon: LayoutDashboard,
    match: (p) => p === "/dashboard",
  },
  {
    href: "/dashboard/graph",
    label: "Knowledge graph",
    Icon: Network,
    match: (p) => p.startsWith("/dashboard/graph"),
  },
];

export function Sidebar() {
  const pathname = usePathname() ?? "";

  return (
    <aside
      data-testid="app-sidebar"
      className="hidden lg:flex lg:w-60 lg:shrink-0 lg:flex-col lg:border-r lg:border-sidebar-border lg:bg-sidebar/80 lg:backdrop-blur-xl"
    >
      <div className="flex h-16 items-center px-5">
        <BrandMark size="md" />
      </div>

      <nav className="flex-1 space-y-1 px-4 py-2" aria-label="Primary">
        {NAV.map(({ href, label, Icon, match }) => {
          const active = match ? match(pathname) : pathname === href;
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              data-testid={`nav-${label.toLowerCase().replace(/\s+/g, "-")}`}
              className={
                "group flex items-center gap-3 rounded-lg px-3.5 py-2.5 text-sm font-medium transition-colors " +
                (active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/80 hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground")
              }
            >
              <Icon
                className={
                  "size-4 transition-colors " +
                  (active
                    ? "text-[color:var(--brand)]"
                    : "text-muted-foreground group-hover:text-foreground")
                }
                aria-hidden="true"
              />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="border-t border-sidebar-border px-5 py-5">
        <div className="flex items-start gap-2.5 rounded-lg bg-sidebar-accent/40 p-3.5 text-xs leading-relaxed text-sidebar-foreground/80">
          <Sparkles
            aria-hidden="true"
            className="mt-0.5 size-3.5 shrink-0 text-[color:var(--accent-violet)]"
          />
          <span>
            Multimodal RAG with a live knowledge graph extracted from your
            uploads.
          </span>
        </div>
      </div>
    </aside>
  );
}
