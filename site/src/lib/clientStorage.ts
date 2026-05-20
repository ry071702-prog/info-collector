const READ_KEY = "readArticles";
const FAVORITES_KEY = "favorites";

type StorageKey = typeof READ_KEY | typeof FAVORITES_KEY;

function canUseStorage(): boolean {
  return typeof window !== "undefined" && typeof window.localStorage !== "undefined";
}

function readSet(key: StorageKey): Set<string> {
  if (!canUseStorage()) {
    return new Set();
  }

  try {
    const parsed = JSON.parse(window.localStorage.getItem(key) ?? "[]");
    return new Set(Array.isArray(parsed) ? parsed.map(String).filter(Boolean) : []);
  } catch {
    return new Set();
  }
}

function writeSet(key: StorageKey, values: Set<string>): void {
  if (!canUseStorage()) {
    return;
  }
  window.localStorage.setItem(key, JSON.stringify([...values]));
}

export function markRead(articleId: string): void {
  if (!articleId) {
    return;
  }
  const reads = readSet(READ_KEY);
  reads.add(articleId);
  writeSet(READ_KEY, reads);
}

export function isRead(articleId: string): boolean {
  return readSet(READ_KEY).has(articleId);
}

export function resetReads(): void {
  if (!canUseStorage()) {
    return;
  }
  window.localStorage.removeItem(READ_KEY);
}

export function favorite(articleId: string): void {
  if (!articleId) {
    return;
  }
  const favorites = readSet(FAVORITES_KEY);
  favorites.add(articleId);
  writeSet(FAVORITES_KEY, favorites);
}

export function unfavorite(articleId: string): void {
  const favorites = readSet(FAVORITES_KEY);
  favorites.delete(articleId);
  writeSet(FAVORITES_KEY, favorites);
}

export function toggleFavorite(articleId: string): boolean {
  if (!articleId) {
    return false;
  }
  const favorites = readSet(FAVORITES_KEY);
  const nextValue = !favorites.has(articleId);
  if (nextValue) {
    favorites.add(articleId);
  } else {
    favorites.delete(articleId);
  }
  writeSet(FAVORITES_KEY, favorites);
  return nextValue;
}

export function isFavorite(articleId: string): boolean {
  return readSet(FAVORITES_KEY).has(articleId);
}

export function favoriteIds(): string[] {
  return [...readSet(FAVORITES_KEY)];
}

export const storageKeys = {
  readArticles: READ_KEY,
  favorites: FAVORITES_KEY,
} as const;
