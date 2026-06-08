import type { SavedItem, SavedItemRow } from "./types";

export function parseTags(value: string | null): string[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed.map((tag) => String(tag)).filter(Boolean) : [];
  } catch {
    return [];
  }
}

export function rowToSavedItem(row: SavedItemRow): SavedItem {
  return {
    ...row,
    tags: parseTags(row.tags),
    importance: row.importance === "S" || row.importance === "A" || row.importance === "B" || row.importance === "C" ? row.importance : "C",
  };
}
