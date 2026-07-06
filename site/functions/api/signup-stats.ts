import { ApiError, emptyResponse, handleApiError, jsonResponse, verifyPasscode } from "../_lib/http";
import type { PagesContext } from "../_lib/types";

// Phase0 需要計測の管理用サマリ。SAVE_PASSCODE で保護。
// GET /api/signup-stats?key=<passcode>
// 返り値: 総数 / ジャンル別人気 / 日次登録数 / 国別 / 平均選択ジャンル数

type WaitlistRow = {
  genres: string | null;
  genre_count: number | null;
  country: string | null;
  created_at: string | null;
};

export const onRequestOptions = async ({ request }: PagesContext) => emptyResponse(request);

export const onRequestGet = async ({ request, env }: PagesContext) => {
  try {
    const url = new URL(request.url);
    const key = url.searchParams.get("key");
    if (!(await verifyPasscode(key, env.SAVE_PASSCODE))) {
      throw new ApiError(401, "Invalid passcode");
    }

    const { results } = await env.DB.prepare(
      "SELECT genres, genre_count, country, created_at FROM waitlist",
    ).all<WaitlistRow>();
    const rows = results ?? [];

    const byGenre: Record<string, number> = {};
    const byDay: Record<string, number> = {};
    const byCountry: Record<string, number> = {};
    let genreTotal = 0;

    for (const row of rows) {
      // ジャンル別
      let genres: string[] = [];
      try {
        const parsed = JSON.parse(row.genres ?? "[]");
        if (Array.isArray(parsed)) genres = parsed.filter((g): g is string => typeof g === "string");
      } catch {
        genres = [];
      }
      for (const slug of genres) byGenre[slug] = (byGenre[slug] ?? 0) + 1;
      genreTotal += row.genre_count ?? genres.length;

      // 日次 (UTC 日付)
      const day = (row.created_at ?? "").slice(0, 10);
      if (day) byDay[day] = (byDay[day] ?? 0) + 1;

      // 国別
      const country = row.country ?? "??";
      byCountry[country] = (byCountry[country] ?? 0) + 1;
    }

    const total = rows.length;
    const genreRanking = Object.entries(byGenre)
      .sort((a, b) => b[1] - a[1])
      .map(([slug, count]) => ({ slug, count }));

    return jsonResponse(request, {
      total,
      avg_genres: total ? Math.round((genreTotal / total) * 10) / 10 : 0,
      genre_ranking: genreRanking,
      by_day: Object.fromEntries(Object.entries(byDay).sort()),
      by_country: Object.fromEntries(Object.entries(byCountry).sort((a, b) => b[1] - a[1])),
    });
  } catch (error) {
    return handleApiError(request, error);
  }
};
