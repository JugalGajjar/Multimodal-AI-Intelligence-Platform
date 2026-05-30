import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeProvider } from "./theme-provider";
import { ThemeToggle } from "./theme-toggle";

describe("<ThemeToggle />", () => {
  const STORAGE_KEY = "mmap-theme";

  beforeEach(() => {
    localStorage.clear();
    document.documentElement.classList.remove("dark");
    // happy-dom polyfills matchMedia but defaults to no-match — make light explicit.
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: false,
      media: q,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
    document.documentElement.classList.remove("dark");
  });

  function renderToggle() {
    return render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
  }

  it("renders three options: Light, Dark, System", () => {
    renderToggle();

    expect(screen.getByTestId("theme-toggle-light")).toBeInTheDocument();
    expect(screen.getByTestId("theme-toggle-dark")).toBeInTheDocument();
    expect(screen.getByTestId("theme-toggle-system")).toBeInTheDocument();
  });

  it("clicking 'Dark' adds the .dark class to <html> and persists to localStorage", async () => {
    renderToggle();

    await userEvent.click(screen.getByTestId("theme-toggle-dark"));

    expect(document.documentElement.classList.contains("dark")).toBe(true);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("dark");
  });

  it("clicking 'Light' removes the .dark class and persists", async () => {
    document.documentElement.classList.add("dark");
    renderToggle();

    await userEvent.click(screen.getByTestId("theme-toggle-light"));

    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem(STORAGE_KEY)).toBe("light");
  });

  it("the active option exposes aria-checked=true", async () => {
    renderToggle();

    await userEvent.click(screen.getByTestId("theme-toggle-dark"));

    expect(screen.getByTestId("theme-toggle-dark")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByTestId("theme-toggle-light")).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });

  it("defaults to 'system' when nothing is stored", () => {
    renderToggle();

    expect(screen.getByTestId("theme-toggle-system")).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });
});
