import { emptyResponse, handleApiError, jsonResponse } from "../_lib/http";
import { rowToSavedItem } from "../_lib/items";
import type { PagesContext, SavedItemRow } from "../_lib/types";

export const onRequestOptions = async ({ request }: PagesContext) => emptyResponse(request);

export const onRequestGet = async ({ request, env }: PagesContext) => {
  try {
    const result = await env.DB.prepare("SELECT * FROM saved_items ORDER BY created_at DESC LIMIT 200").all<SavedItemRow>();
    const items = (result.results ?? []).map(rowToSavedItem);
    return jsonResponse(request, { items });
  } catch (error) {
    return handleApiError(request, error);
  }
};
