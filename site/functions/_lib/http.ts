import type { Env, PagesContext } from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function corsHeaders(request: Request): HeadersInit {
  const origin = request.headers.get("Origin");
  const requestOrigin = new URL(request.url).origin;
  if (!origin || origin !== requestOrigin) return {};
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
    Vary: "Origin",
  };
}

export function jsonResponse(request: Request, data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      ...corsHeaders(request),
    },
  });
}

export function emptyResponse(request: Request, status = 204): Response {
  return new Response(null, {
    status,
    headers: corsHeaders(request),
  });
}

export async function readJsonBody<T extends Record<string, unknown>>(request: Request): Promise<T> {
  const contentType = request.headers.get("Content-Type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new ApiError(415, "Content-Type must be application/json");
  }
  try {
    const body = await request.json();
    if (!body || typeof body !== "object" || Array.isArray(body)) {
      throw new Error("invalid body");
    }
    return body as T;
  } catch {
    throw new ApiError(400, "Invalid JSON body");
  }
}

async function sha256(value: string): Promise<Uint8Array> {
  const data = new TextEncoder().encode(value);
  const digest = await crypto.subtle.digest("SHA-256", data);
  return new Uint8Array(digest);
}

export async function verifyPasscode(provided: unknown, expected: string | undefined): Promise<boolean> {
  if (typeof expected !== "string" || expected.length === 0) return false;
  const providedValue = typeof provided === "string" ? provided : "";
  const [providedHash, expectedHash] = await Promise.all([sha256(providedValue), sha256(expected)]);
  let diff = providedHash.length ^ expectedHash.length;
  const length = Math.max(providedHash.length, expectedHash.length);
  for (let index = 0; index < length; index += 1) {
    diff |= (providedHash[index] ?? 0) ^ (expectedHash[index] ?? 0);
  }
  return diff === 0;
}

export async function requirePasscode(request: Request, env: Env, provided: unknown): Promise<void> {
  if (!(await verifyPasscode(provided, env.SAVE_PASSCODE))) {
    throw new ApiError(401, "Invalid passcode");
  }
}

export async function handleApiError(request: Request, error: unknown): Promise<Response> {
  if (error instanceof ApiError) {
    return jsonResponse(request, { error: error.message }, error.status);
  }
  console.error(error);
  return jsonResponse(request, { error: "Internal Server Error" }, 500);
}

export function methodNotAllowed(context: PagesContext): Response {
  return jsonResponse(context.request, { error: "Method Not Allowed" }, 405);
}
