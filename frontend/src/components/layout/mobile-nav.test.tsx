import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/dashboard",
}));

import { MobileNav } from "./mobile-nav";
import { ABOUT_ITEM, NAV_ITEMS } from "./nav-items";

describe("<MobileNav />", () => {
  it("renders every item from the shared NAV_ITEMS list", () => {
    render(<MobileNav open onClose={() => {}} />);
    for (const item of NAV_ITEMS) {
      expect(
        screen.getByRole("link", { name: new RegExp(item.label, "i") }),
      ).toBeInTheDocument();
    }
  });

  it("includes the About link (mobile users can reach /dashboard/about)", () => {
    render(<MobileNav open onClose={() => {}} />);
    expect(
      screen.getByRole("link", { name: new RegExp(ABOUT_ITEM.label, "i") }),
    ).toHaveAttribute("href", ABOUT_ITEM.href);
  });

  it("does not render anything when open=false", () => {
    render(<MobileNav open={false} onClose={() => {}} />);
    expect(screen.queryByTestId("mobile-nav")).not.toBeInTheDocument();
  });

  it("marks the current pathname as aria-current", () => {
    render(<MobileNav open onClose={() => {}} />);
    // usePathname is mocked to /dashboard — Dashboard link should be current.
    const dashLink = screen.getByRole("link", { name: /^dashboard$/i });
    expect(dashLink).toHaveAttribute("aria-current", "page");
    // Non-matching links should not.
    const chatsLink = screen.getByRole("link", { name: /^chats$/i });
    expect(chatsLink).not.toHaveAttribute("aria-current");
  });
});
