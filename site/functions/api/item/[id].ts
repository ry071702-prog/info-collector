import { ApiError, emptyResponse, handleApiError, jsonResponse, readJsonBody, requirePasscode } from "../../_lib/http";
import type { PagesContext } from "../../_lib/types";

type DeleteBody = {
  passcode?: unknown;
};

function idParam(params: PagesContext["params"]): string {
  const value = params.id;
  return Array.isArray(value) ? value[0] ?? "" : value ?? "";
}

export const onRequestOptions = async ({ request }: PagesContext) => emptyResponse(request);

export const onRequestDelete = async ({ request, env, params }: PagesContext) => {
  try {
    const id = idParam(params);
    if (!id) throw new ApiError(400, "id is required");

    const body = await readJsonBody<DeleteBody>(request);
    await requirePasscode(request, env, body.passcode);

    await env.DB.prepare("DELETE FROM saved_items WHERE id = ?").bind(id).run();
    return jsonResponse(request, { ok: true, id });
  } catch (error) {
    return handleApiError(request, error);
  }
};
