export interface D1PreparedStatement {
  bind(...values: unknown[]): D1PreparedStatement;
  all<T = Record<string, unknown>>(): Promise<{ results?: T[] }>;
  first<T = Record<string, unknown>>(): Promise<T | null>;
  run(): Promise<unknown>;
}

export interface D1Database {
  prepare(query: string): D1PreparedStatement;
}

export interface Env {
  DB: D1Database;
  GEMINI_API_KEY: string;
  SAVE_PASSCODE: string;
}

export interface PagesContext {
  request: Request;
  env: Env;
  params: Record<string, string | string[]>;
}

export interface SavedItem {
  id: string;
  url: string | null;
  title: string;
  summary: string;
  tags: string[];
  category: string;
  importance: "S" | "A" | "B" | "C";
  note: string | null;
  domain: string | null;
  favicon_url: string | null;
  image_url: string | null;
  created_at: string;
}

export interface SavedItemRow extends Omit<SavedItem, "tags"> {
  tags: string | null;
}
