import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";

class MemoryStorage implements Storage {
  private store = new Map<string, string>();

  get length(): number {
    return this.store.size;
  }
  clear(): void {
    this.store.clear();
  }
  getItem(key: string): string | null {
    return this.store.get(key) ?? null;
  }
  key(index: number): string | null {
    return Array.from(this.store.keys())[index] ?? null;
  }
  removeItem(key: string): void {
    this.store.delete(key);
  }
  setItem(key: string, value: string): void {
    this.store.set(key, String(value));
  }
}

const localStoragePolyfill = new MemoryStorage();
const sessionStoragePolyfill = new MemoryStorage();

// Node 26 ships an experimental `localStorage` global that's undefined unless
// `--localstorage-file` is provided, which shadows happy-dom. Override on both
// `globalThis` and `window` so application code and tests see a working impl.
Object.defineProperty(globalThis, "localStorage", {
  value: localStoragePolyfill,
  configurable: true,
  writable: true,
});
Object.defineProperty(globalThis, "sessionStorage", {
  value: sessionStoragePolyfill,
  configurable: true,
  writable: true,
});
if (typeof window !== "undefined") {
  Object.defineProperty(window, "localStorage", {
    value: localStoragePolyfill,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(window, "sessionStorage", {
    value: sessionStoragePolyfill,
    configurable: true,
    writable: true,
  });
}

beforeEach(() => {
  localStoragePolyfill.clear();
  sessionStoragePolyfill.clear();
});

afterEach(() => {
  cleanup();
});
