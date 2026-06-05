import { describe, expect, it } from "vitest";

import {
  evaluatePassword,
  firstPasswordError,
  MAX_LEN,
  MIN_LEN,
} from "./password-validator";

describe("evaluatePassword", () => {
  it("returns all rules satisfied for a strong password", () => {
    const rules = evaluatePassword("StrongP@ss1");
    expect(rules.every((r) => r.ok)).toBe(true);
  });

  it("flags missing classes individually", () => {
    const rules = evaluatePassword("abcdefgh");
    const failing = rules.filter((r) => !r.ok).map((r) => r.id);
    expect(failing).toContain("upper");
    expect(failing).toContain("digit");
    expect(failing).toContain("special");
  });

  it("flags product-name substrings (case-insensitive)", () => {
    const rules = evaluatePassword("Mmap1@PassWord");
    expect(rules.find((r) => r.id === "no-product")?.ok).toBe(false);
  });

  it("flags email local-part inside the password", () => {
    const rules = evaluatePassword("AliceWonder1!", "alicewonder@x.io");
    expect(rules.find((r) => r.id === "no-email")?.ok).toBe(false);
  });

  it("does not block short local-parts", () => {
    const rules = evaluatePassword("Wonder1Land!", "al@x.io");
    expect(rules.find((r) => r.id === "no-email")?.ok).toBe(true);
  });

  it("rejects too-long passwords", () => {
    const rules = evaluatePassword("A1!" + "x".repeat(MAX_LEN));
    expect(rules.find((r) => r.id === "length")?.ok).toBe(false);
  });

  it("accepts boundary minimum length", () => {
    expect(MIN_LEN).toBe(8);
    const rules = evaluatePassword("Ab1!cdEf");
    expect(rules.find((r) => r.id === "length")?.ok).toBe(true);
  });
});

describe("firstPasswordError", () => {
  it("returns null for a strong password", () => {
    expect(firstPasswordError("StrongP@ss1")).toBeNull();
  });

  it("returns a message for a weak password", () => {
    const msg = firstPasswordError("abcdefgh");
    expect(msg).toBeTruthy();
    expect(msg).toMatch(/password/i);
  });
});
