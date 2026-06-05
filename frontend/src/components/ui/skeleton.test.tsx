import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Skeleton } from "./skeleton";

describe("<Skeleton />", () => {
  it("renders a pulse element", () => {
    render(<Skeleton className="h-4 w-1/2" />);
    const el = screen.getByTestId("skeleton");
    expect(el.className).toMatch(/animate-pulse/);
    expect(el.className).toMatch(/w-1\/2/);
  });
});
