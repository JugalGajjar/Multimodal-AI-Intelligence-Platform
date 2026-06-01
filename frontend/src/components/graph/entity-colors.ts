// Tailwind 500 swatches; readable on both light and dark backgrounds.
export const ENTITY_TYPE_COLORS: Record<string, string> = {
  Person: "#f97316", // orange-500
  Organization: "#a855f7", // purple-500
  Location: "#10b981", // emerald-500
  Concept: "#3b82f6", // blue-500
  Technology: "#06b6d4", // cyan-500
  Product: "#ec4899", // pink-500
  Event: "#eab308", // yellow-500
  Date: "#94a3b8", // slate-400
};

const DEFAULT_COLOR = "#94a3b8"; // slate-400 — same as Date for unknown types

export function colorForEntityType(type: string | undefined | null): string {
  if (!type) return DEFAULT_COLOR;
  return ENTITY_TYPE_COLORS[type] ?? DEFAULT_COLOR;
}

export const ENTITY_TYPE_LEGEND: { type: string; color: string }[] = Object.entries(
  ENTITY_TYPE_COLORS,
).map(([type, color]) => ({ type, color }));
