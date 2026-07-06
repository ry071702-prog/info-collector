import { ApiError, emptyResponse, handleApiError, jsonResponse, readJsonBody } from "../_lib/http";
import type { PagesContext } from "../_lib/types";

type SignupBody = {
  email?: unknown;
  genres?: unknown;
  referrer?: unknown;
};

// 簡易メール検証（厳密なRFCではなく実用レベル）
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const MAX_GENRES = 60;
const MAX_SLUG_LEN = 40;
const SLUG_RE = /^[a-z0-9-]+$/;

function cleanGenres(value: unknown): string[] {
  if (!Array.isArray(value)) throw new ApiError(400, "genres must be an array");
  const seen = new Set<string>();
  for (const raw of value) {
    if (typeof raw !== "string") continue;
    const slug = raw.trim();
    if (!slug || slug.length > MAX_SLUG_LEN || !SLUG_RE.test(slug)) continue;
    seen.add(slug);
    if (seen.size > MAX_GENRES) break;
  }
  if (seen.size === 0) throw new ApiError(400, "興味のあるジャンルを1つ以上選んでください");
  return [...seen];
}

export const onRequestOptions = async ({ request }: PagesContext) => emptyResponse(request);

// 登録数（ソーシャルプルーフ用・公開）
export const onRequestGet = async ({ request, env }: PagesContext) => {
  try {
    const row = await env.DB.prepare("SELECT COUNT(*) AS n FROM waitlist").first<{ n: number }>();
    return jsonResponse(request, { count: row?.n ?? 0 });
  } catch (error) {
    return handleApiError(request, error);
  }
};

export const onRequestPost = async ({ request, env }: PagesContext) => {
  try {
    const body = await readJsonBody<SignupBody>(request);

    const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
    if (!email || email.length > 254 || !EMAIL_RE.test(email)) {
      throw new ApiError(400, "メールアドレスの形式が正しくありません");
    }
    const genres = cleanGenres(body.genres);
    const referrer = typeof body.referrer === "string" ? body.referrer.slice(0, 300) : null;

    const now = new Date().toISOString();
    const cf = (request as Request & { cf?: { country?: string } }).cf;
    const country = cf?.country ?? null;
    const userAgent = request.headers.get("User-Agent")?.slice(0, 300) ?? null;
    const genresJson = JSON.stringify(genres);

    // email 一意。既存なら購読ジャンルを更新（UPSERT）。
    await env.DB.prepare(
      `INSERT INTO waitlist (id, email, genres, genre_count, country, referrer, user_agent, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
       ON CONFLICT(email) DO UPDATE SET
         genres = excluded.genres,
         genre_count = excluded.genre_count,
         referrer = COALESCE(waitlist.referrer, excluded.referrer),
         updated_at = excluded.updated_at`,
    )
      .bind(
        crypto.randomUUID(),
        email,
        genresJson,
        genres.length,
        country,
        referrer,
        userAgent,
        now,
        now,
      )
      .run();

    return jsonResponse(request, { ok: true, genres: genres.length }, 201);
  } catch (error) {
    return handleApiError(request, error);
  }
};
