import { ApiError, emptyResponse, handleApiError, jsonResponse, readJsonBody, requirePasscode } from "../_lib/http";
import { rowToSavedItem } from "../_lib/items";
import { fetchPageMetadata, normalizeHttpUrl, type PageMetadata } from "../_lib/metadata";
import { summarizeWithGemini, type GeminiSummary } from "../_lib/gemini";
import type { PagesContext, SavedItem, SavedItemRow } from "../_lib/types";

type SaveBody = {
  url?: unknown;
  note?: unknown;
  passcode?: unknown;
};

function fallbackMetadata(url: URL | null, note: string): PageMetadata {
  return {
    url: url?.toString() ?? "",
    domain: url?.hostname ?? "manual",
    title: note ? note.slice(0, 80) : url?.toString() ?? "保存メモ",
    description: "",
    image_url: null,
    favicon_url: url ? new URL("/favicon.ico", url).toString() : null,
  };
}

function itemFromParts(input: {
  id: string;
  metadata: PageMetadata;
  summary: GeminiSummary | null;
  note: string;
  createdAt: string;
}): SavedItem {
  return {
    id: input.id,
    url: input.metadata.url || null,
    title: input.metadata.title || "無題",
    summary: input.summary?.summary || input.metadata.description || "",
    tags: input.summary?.tags ?? [],
    category: input.summary?.category || "other",
    importance: input.summary?.importance || "C",
    note: input.note || null,
    domain: input.metadata.domain || null,
    favicon_url: input.metadata.favicon_url,
    image_url: input.metadata.image_url,
    created_at: input.createdAt,
  };
}

export const onRequestOptions = async ({ request }: PagesContext) => emptyResponse(request);

export const onRequestPost = async ({ request, env }: PagesContext) => {
  try {
    const body = await readJsonBody<SaveBody>(request);
    await requirePasscode(request, env, body.passcode);

    const note = typeof body.note === "string" ? body.note.trim().slice(0, 2000) : "";
    const parsedUrl = normalizeHttpUrl(body.url);
    if (!parsedUrl && !note) {
      throw new ApiError(400, "url or note is required");
    }

    let metadata = fallbackMetadata(parsedUrl, note);
    if (parsedUrl) {
      try {
        metadata = await fetchPageMetadata(parsedUrl);
      } catch (error) {
        console.warn("metadata extraction skipped", error);
      }
    }

    const summary = await summarizeWithGemini({
      apiKey: env.GEMINI_API_KEY,
      title: metadata.title,
      description: metadata.description,
      note,
      domain: metadata.domain,
    });

    const item = itemFromParts({
      id: crypto.randomUUID(),
      metadata,
      summary,
      note,
      createdAt: new Date().toISOString(),
    });

    await env.DB.prepare(
      `INSERT INTO saved_items
        (id, url, title, summary, tags, category, importance, note, domain, favicon_url, image_url, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
      .bind(
        item.id,
        item.url,
        item.title,
        item.summary,
        JSON.stringify(item.tags),
        item.category,
        item.importance,
        item.note,
        item.domain,
        item.favicon_url,
        item.image_url,
        item.created_at,
      )
      .run();

    const saved = await env.DB.prepare("SELECT * FROM saved_items WHERE id = ?").bind(item.id).first<SavedItemRow>();
    return jsonResponse(request, { item: saved ? rowToSavedItem(saved) : item }, 201);
  } catch (error) {
    return handleApiError(request, error);
  }
};
