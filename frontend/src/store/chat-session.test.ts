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
    if (typeof window !== "undefined") {
      window.sessionStorage.clear();
    }
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

  it("persists chatId + turns to sessionStorage across mount cycles", () => {
    const s = useChatSessionStore.getState();
    s.setChatId("c-persist");
    s.addTurn("q-persist", fakeResponse("a-persist"));

    // Persist middleware writes synchronously for JSON+sessionStorage.
    const raw = window.sessionStorage.getItem("mmap-chat-session");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!);
    expect(parsed.state.chatId).toBe("c-persist");
    expect(parsed.state.turns).toHaveLength(1);
    expect(parsed.state.turns[0].question).toBe("q-persist");
  });

  it("does not persist volatile fields (functions stay in-memory)", () => {
    useChatSessionStore.getState().setChatId("c-1");
    const raw = window.sessionStorage.getItem("mmap-chat-session");
    const parsed = JSON.parse(raw!);
    // Only chatId + turns; no setChatId / addTurn / reset in the payload.
    expect(Object.keys(parsed.state).sort()).toEqual(["chatId", "turns"]);
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
