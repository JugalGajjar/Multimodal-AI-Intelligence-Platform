import { describe, expect, it } from "vitest";

import {
  ENTITY_TYPE_COLORS,
  ENTITY_TYPE_LEGEND,
  colorForEntityType,
} from "./entity-colors";

describe("entity-colors", () => {
  it("returns specific colors for each known type", () => {
    expect(colorForEntityType("Person")).toBe(ENTITY_TYPE_COLORS.Person);
    expect(colorForEntityType("Technology")).toBe(ENTITY_TYPE_COLORS.Technology);
    expect(colorForEntityType("Concept")).toBe(ENTITY_TYPE_COLORS.Concept);
  });

  it("falls back to the slate default for unknown types", () => {
    const fallback = colorForEntityType("Vegetable");
    expect(fallback).toMatch(/^#/);
    // sanity: it's not the same as a distinctive specific type
    expect(fallback).not.toBe(ENTITY_TYPE_COLORS.Person);
  });

  it("falls back to the slate default for null/undefined", () => {
    expect(colorForEntityType(null)).toMatch(/^#/);
    expect(colorForEntityType(undefined)).toMatch(/^#/);
    expect(colorForEntityType("")).toMatch(/^#/);
  });

  it("legend has all known types", () => {
    const types = ENTITY_TYPE_LEGEND.map((e) => e.type);
    expect(types).toEqual(expect.arrayContaining(Object.keys(ENTITY_TYPE_COLORS)));
    expect(ENTITY_TYPE_LEGEND).toHaveLength(Object.keys(ENTITY_TYPE_COLORS).length);
  });

  it("every legend color is a valid hex string", () => {
    for (const entry of ENTITY_TYPE_LEGEND) {
      expect(entry.color).toMatch(/^#[0-9a-f]{3,8}$/i);
    }
  });
});
