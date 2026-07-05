import {
  BookOpen,
  Files,
  History,
  LayoutDashboard,
  Network,
  Settings,
} from "lucide-react";

/** Single source of truth for the app's primary nav. Consumed by both the
 *  desktop <Sidebar /> and the mobile <MobileNav /> so a new page doesn't
 *  have to be added in two places (that's how Chats went missing on mobile). */
export type NavItem = {
  href: string;
  label: string;
  Icon: typeof LayoutDashboard;
  /** Optional custom active-match predicate. Defaults to exact-match. */
  match?: (pathname: string) => boolean;
};

export const NAV_ITEMS: NavItem[] = [
  {
    href: "/dashboard",
    label: "Dashboard",
    Icon: LayoutDashboard,
    match: (p) => p === "/dashboard",
  },
  {
    href: "/dashboard/documents",
    label: "Your documents",
    Icon: Files,
    match: (p) => p.startsWith("/dashboard/documents"),
  },
  {
    href: "/dashboard/chats",
    label: "Chats",
    Icon: History,
    match: (p) => p.startsWith("/dashboard/chats"),
  },
  {
    href: "/dashboard/graph",
    label: "Knowledge graph",
    Icon: Network,
    match: (p) => p.startsWith("/dashboard/graph"),
  },
  {
    href: "/dashboard/settings",
    label: "Settings",
    Icon: Settings,
    match: (p) => p.startsWith("/dashboard/settings"),
  },
];

/** About link — rendered separately from the primary nav on desktop (as a
 *  richer footer card) but as a plain row on mobile. Kept out of NAV_ITEMS
 *  so its distinct visual treatment on each surface stays intentional. */
export const ABOUT_ITEM: NavItem = {
  href: "/dashboard/about",
  label: "About MMAP",
  Icon: BookOpen,
  match: (p) => p.startsWith("/dashboard/about"),
};
