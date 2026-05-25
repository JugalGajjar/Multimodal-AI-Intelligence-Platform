import { beforeEach, describe, expect, it } from "vitest";

import { useAuthStore } from "./auth";

describe("useAuthStore", () => {
  beforeEach(() => {
    localStorage.clear();
    useAuthStore.getState().clearSession();
  });

  it("starts unauthenticated", () => {
    const state = useAuthStore.getState();

    expect(state.user).toBeNull();
    expect(state.token).toBeNull();
    expect(state.isAuthenticated).toBe(false);
  });

  it("setSession marks as authenticated and stores user + token", () => {
    useAuthStore.getState().setSession(
      { id: "u-1", email: "a@b.com" },
      "tok-abc",
    );

    const state = useAuthStore.getState();
    expect(state.user).toEqual({ id: "u-1", email: "a@b.com" });
    expect(state.token).toBe("tok-abc");
    expect(state.isAuthenticated).toBe(true);
  });

  it("clearSession resets to unauthenticated", () => {
    useAuthStore.getState().setSession(
      { id: "u-1", email: "a@b.com" },
      "tok-abc",
    );

    useAuthStore.getState().clearSession();

    const state = useAuthStore.getState();
    expect(state.user).toBeNull();
    expect(state.token).toBeNull();
    expect(state.isAuthenticated).toBe(false);
  });

  it("persists user and token to localStorage under mmap-auth", () => {
    useAuthStore.getState().setSession(
      { id: "u-1", email: "a@b.com" },
      "tok-abc",
    );

    const raw = localStorage.getItem("mmap-auth");
    expect(raw).not.toBeNull();
    const parsed = JSON.parse(raw!);
    expect(parsed.state.user).toEqual({ id: "u-1", email: "a@b.com" });
    expect(parsed.state.token).toBe("tok-abc");
  });

  it("does not persist isAuthenticated (derived flag)", () => {
    useAuthStore.getState().setSession(
      { id: "u-1", email: "a@b.com" },
      "tok-abc",
    );

    const parsed = JSON.parse(localStorage.getItem("mmap-auth")!);
    expect(parsed.state.isAuthenticated).toBeUndefined();
  });
});
