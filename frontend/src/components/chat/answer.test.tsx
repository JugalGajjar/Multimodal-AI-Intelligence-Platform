import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Answer imports the canvas-heavy KnowledgeGraph; stub it out to keep tests
// fast and jsdom-safe.
vi.mock("@/components/graph/knowledge-graph", () => ({
  KnowledgeGraph: () => <div data-testid="kg-stub" />,
}));

import { Answer } from "./answer";
import type { ChatResponse } from "@/lib/chat-api";

function baseResponse(answer: string): ChatResponse {
  return {
    answer,
    citations: [],
    entities_used: [],
    model: "test-model",
    used_context: false,
    used_graph: false,
  };
}

describe("<Answer />", () => {
  describe("safe HTML rendering", () => {
    it("renders <br> as a real line break, not literal text", () => {
      const raw =
        "First bullet content.<br>• Second bullet<br/>• Third<br /> • Fourth";
      render(<Answer response={baseResponse(raw)} />);
      const text = screen.getByTestId("chat-answer-text");
      // Literal "<br>" never leaks into the rendered text.
      expect(text.textContent).not.toMatch(/<br/i);
      expect(text.textContent).not.toMatch(/&lt;br/i);
      // <br> lands as an actual DOM element in the output.
      expect(text.querySelectorAll("br").length).toBeGreaterThanOrEqual(3);
      // Original text content is preserved.
      expect(text.textContent).toContain("First bullet content.");
      expect(text.textContent).toContain("Second bullet");
      expect(text.textContent).toContain("Third");
      expect(text.textContent).toContain("Fourth");
    });

    it("still renders standard markdown (bold, code)", () => {
      const raw = "This is **bold** and this is `code`.";
      render(<Answer response={baseResponse(raw)} />);
      const text = screen.getByTestId("chat-answer-text");
      expect(text.querySelector("strong")?.textContent).toBe("bold");
      expect(text.querySelector("code")?.textContent).toBe("code");
    });

    it("leaves plain text unchanged", () => {
      const raw = "Just a normal paragraph.";
      render(<Answer response={baseResponse(raw)} />);
      expect(screen.getByTestId("chat-answer-text").textContent).toBe(
        "Just a normal paragraph.",
      );
    });

    it("renders inline emphasis tags the model might reach for", () => {
      const raw = "<em>emphasised</em> and <strong>heavy</strong>";
      render(<Answer response={baseResponse(raw)} />);
      const text = screen.getByTestId("chat-answer-text");
      expect(text.querySelector("em")?.textContent).toBe("emphasised");
      expect(text.querySelector("strong")?.textContent).toBe("heavy");
    });
  });

  describe("prompt-injection / XSS defence", () => {
    // Suppress noisy rehype-sanitize warnings during these tests.
    let warnSpy: ReturnType<typeof vi.spyOn>;
    beforeEach(() => {
      warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    });
    afterEach(() => warnSpy.mockRestore());

    it("strips <script> tags produced by prompt injection", () => {
      const raw =
        "answer text<script>window.__pwned = true</script> more text";
      render(<Answer response={baseResponse(raw)} />);
      const text = screen.getByTestId("chat-answer-text");
      // Script element is removed from the DOM entirely.
      expect(text.querySelector("script")).toBeNull();
      // The window global was NEVER assigned (rehype-sanitize strips before
      // React inserts anything into the DOM, so the script never runs).
      expect(
        (window as unknown as { __pwned?: boolean }).__pwned,
      ).toBeUndefined();
    });

    it("strips <iframe> src attempts", () => {
      const raw = 'text <iframe src="https://evil.example/steal"></iframe>';
      render(<Answer response={baseResponse(raw)} />);
      const text = screen.getByTestId("chat-answer-text");
      expect(text.querySelector("iframe")).toBeNull();
    });

    it("strips inline event handler attributes", () => {
      const raw = '<span onclick="window.__click = true">click me</span>';
      render(<Answer response={baseResponse(raw)} />);
      const text = screen.getByTestId("chat-answer-text");
      const span = text.querySelector("span");
      // Span may be kept, but the onclick attribute must be gone.
      expect(span?.getAttribute("onclick")).toBeNull();
    });

    it("strips javascript: URLs on <a href>", () => {
      const raw =
        "check [this link](javascript:window.__jsUrl=true) — do not click";
      render(<Answer response={baseResponse(raw)} />);
      const text = screen.getByTestId("chat-answer-text");
      const link = text.querySelector("a");
      // Sanitizer either drops the anchor entirely, or keeps the anchor but
      // strips the javascript: href. Either way, no `href` starting with
      // "javascript:" may reach the DOM.
      const href = link?.getAttribute("href");
      expect(href ?? "").not.toMatch(/^javascript:/i);
      // Defence-in-depth: the payload never ran.
      expect(
        (window as unknown as { __jsUrl?: boolean }).__jsUrl,
      ).toBeUndefined();
    });

    it("strips <object> and <embed> tags", () => {
      const raw =
        '<object data="evil.swf"></object> and <embed src="evil.swf">';
      render(<Answer response={baseResponse(raw)} />);
      const text = screen.getByTestId("chat-answer-text");
      expect(text.querySelector("object")).toBeNull();
      expect(text.querySelector("embed")).toBeNull();
    });

    it("strips <style> tags (CSS attack vector)", () => {
      const raw =
        '<style>body{background:url("https://evil.example/beacon")}</style> visible text';
      render(<Answer response={baseResponse(raw)} />);
      const text = screen.getByTestId("chat-answer-text");
      // The <style> element must not survive — otherwise the CSS rule would
      // be applied and any background-url would beacon. The stripped tag's
      // text content may render as inert visible text (annoying, not
      // dangerous) so we don't assert on textContent here.
      expect(text.querySelector("style")).toBeNull();
      // Ambient defence: page background must not have been altered.
      expect(document.body.style.background).toBe("");
    });
  });
});
