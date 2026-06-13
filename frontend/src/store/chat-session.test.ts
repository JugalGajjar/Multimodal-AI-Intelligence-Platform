import { beforeEach, describe, expect, it } from "vitest";

import type { ChatResponse } from "@/lib/chat-api";
import { useAuthStore } from "@/store/auth";
import { useChatSessionStore } from "./chat-session";

function fakeResponse(answer: string): ChatResponse {
  return {
    answer,
    citations: [],
    entities_used: [],
    model: "m",
    used_context: false,
    used_graph: false,
  };
}

describe("chat-session store", () => {
  beforeEach(() => {
    useChatSessionStore.getState().reset();
  });

  it("starts empty with no chat id", () => {
    const s = useChatSessionStore.getState();
    expect(s.chatId).toBeNull();
    expect(s.turns).toEqual([]);
  });

  it("accumulates turns in order with unique ids", () => {
    const s = useChatSessionStore.getState();
    s.addTurn("q1", fakeResponse("a1"));
    s.addTurn("q2", fakeResponse("a2"));

    const { turns } = useChatSessionStore.getState();
    expect(turns.map((t) => t.question)).toEqual(["q1", "q2"]);
    expect(turns[0].id).not.toBe(turns[1].id);
  });

  it("reset clears chat id and turns", () => {
    const s = useChatSessionStore.getState();
    s.setChatId("c-1");
    s.addTurn("q", fakeResponse("a"));
    s.reset();

    const after = useChatSessionStore.getState();
    expect(after.chatId).toBeNull();
    expect(after.turns).toEqual([]);
  });

  it("auto-resets when the auth session is cleared (prevents leaks across users)", () => {
    // Simulate user A logged in with an in-flight chat.
    useAuthStore.getState().setSession({ id: "u-A", email: "a@x.com" }, "tok-A");
    const s = useChatSessionStore.getState();
    s.setChatId("chat-of-user-A");
    s.addTurn("private question", fakeResponse("private answer"));

    // User A logs out.
    useAuthStore.getState().clearSession();

    const after = useChatSessionStore.getState();
    expect(after.chatId).toBeNull();
    expect(after.turns).toEqual([]);
  });
});
