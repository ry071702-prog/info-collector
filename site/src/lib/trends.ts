import {
  genreColors,
  genreLabels,
  genres,
  sourceKey,
  sourceLabel,
  type Article,
  type Genre,
  type Priority,
} from "./articles";

export interface SummaryStats {
  totalArticles: number;
  todayArticles: number;
  activeSources: number;
  averageImportance: number | null;
  averageImportanceLabel: string;
}

export interface DailyGenreCount {
  date: string;
  label: string;
  total: number;
  genres: Record<Genre, number>;
}

export interface GenreShare {
  genre: Genre;
  label: string;
  count: number;
  color: string;
  percentage: number;
}

export interface SourceRank {
  key: string;
  label: string;
  count: number;
  percentage: number;
}

export interface HourBucket {
  key: string;
  label: string;
  count: number;
  intensity: number;
}

export interface TrendsData {
  referenceDate: Date;
  articles30d: Article[];
  summary: SummaryStats;
  dailyCounts: DailyGenreCount[];
  genreShares: GenreShare[];
  topSources: SourceRank[];
  activeHours: HourBucket[];
}

const importanceScores: Record<Priority, number> = {
  S: 4,
  A: 3,
  B: 2,
  C: 1,
};

const formatter = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

function validDate(value: string): Date | null {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function dayKey(date: Date): string {
  return formatter.format(date).replaceAll("/", "-");
}

function labelForDay(date: Date): string {
  return new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    month: "numeric",
    day: "numeric",
  }).format(date);
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setUTCDate(next.getUTCDate() + days);
  return next;
}

function startOfJstDay(date: Date): Date {
  const key = dayKey(date);
  return new Date(`${key}T00:00:00+09:00`);
}

function priorityLabel(score: number | null): string {
  if (score === null) {
    return "-";
  }
  if (score >= 3.5) return "S相当";
  if (score >= 2.5) return "A相当";
  if (score >= 1.5) return "B相当";
  return "C相当";
}

export function buildTrendsData(articles: Article[], generatedAt?: string): TrendsData {
  const generatedDate = generatedAt ? validDate(generatedAt) : null;
  const latestArticleDate = articles.map((article) => validDate(article.timestamp)).filter((date): date is Date => date !== null).sort((a, b) => b.getTime() - a.getTime())[0];
  const referenceDate = generatedDate ?? latestArticleDate ?? new Date();
  const todayStart = startOfJstDay(referenceDate);
  const windowStart = addDays(todayStart, -29);
  const weekStart = addDays(todayStart, -6);

  const articles30d = articles.filter((article) => {
    const timestamp = validDate(article.timestamp);
    return timestamp !== null && timestamp >= windowStart && timestamp <= referenceDate;
  });

  const dailyMap = new Map<string, DailyGenreCount>();
  for (let offset = 0; offset < 30; offset += 1) {
    const date = addDays(windowStart, offset);
    dailyMap.set(dayKey(date), {
      date: dayKey(date),
      label: labelForDay(date),
      total: 0,
      genres: { games: 0, anime: 0, disney: 0 },
    });
  }

  const genreCounts = new Map<Genre, number>(genres.map((genre) => [genre, 0]));
  const sourceCounts = new Map<string, { label: string; count: number }>();
  const hourCounts = new Map<string, number>();
  let importanceTotal = 0;
  let importanceCount = 0;

  for (const article of articles30d) {
    const timestamp = validDate(article.timestamp);
    if (timestamp === null) {
      continue;
    }

    const dateKey = dayKey(timestamp);
    const daily = dailyMap.get(dateKey);
    if (daily) {
      daily.total += 1;
      daily.genres[article.genre] = (daily.genres[article.genre] ?? 0) + 1;
    }

    genreCounts.set(article.genre, (genreCounts.get(article.genre) ?? 0) + 1);

    const key = sourceKey(article);
    const existing = sourceCounts.get(key);
    sourceCounts.set(key, { label: existing?.label ?? sourceLabel(article), count: (existing?.count ?? 0) + 1 });

    const score = importanceScores[article.final_priority];
    if (score !== undefined) {
      importanceTotal += score;
      importanceCount += 1;
    }

    if (timestamp >= weekStart) {
      const jstHour = Number(
        new Intl.DateTimeFormat("ja-JP", {
          timeZone: "Asia/Tokyo",
          hour: "2-digit",
          hour12: false,
        }).format(timestamp),
      );
      const bucketStart = Math.floor(jstHour / 4) * 4;
      const bucketKey = String(bucketStart).padStart(2, "0");
      hourCounts.set(bucketKey, (hourCounts.get(bucketKey) ?? 0) + 1);
    }
  }

  const totalArticles = articles30d.length;
  const averageImportance = importanceCount > 0 ? importanceTotal / importanceCount : null;
  const topSourceMax = Math.max(1, ...[...sourceCounts.values()].map((source) => source.count));
  const hourMax = Math.max(1, ...hourCounts.values());

  return {
    referenceDate,
    articles30d,
    summary: {
      totalArticles,
      todayArticles: articles30d.filter((article) => {
        const timestamp = validDate(article.timestamp);
        return timestamp !== null && dayKey(timestamp) === dayKey(referenceDate);
      }).length,
      activeSources: sourceCounts.size,
      averageImportance,
      averageImportanceLabel: priorityLabel(averageImportance),
    },
    dailyCounts: [...dailyMap.values()],
    genreShares: genres.map((genre) => {
      const count = genreCounts.get(genre) ?? 0;
      return {
        genre,
        label: genreLabels[genre],
        count,
        color: genreColors[genre],
        percentage: totalArticles > 0 ? (count / totalArticles) * 100 : 0,
      };
    }),
    topSources: [...sourceCounts.entries()]
      .map(([key, source]) => ({
        key,
        label: source.label,
        count: source.count,
        percentage: (source.count / topSourceMax) * 100,
      }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "ja"))
      .slice(0, 10),
    activeHours: [0, 4, 8, 12, 16, 20].map((hour) => {
      const key = String(hour).padStart(2, "0");
      const count = hourCounts.get(key) ?? 0;
      return {
        key,
        label: `${key}:00-${String(hour + 3).padStart(2, "0")}:59`,
        count,
        intensity: count / hourMax,
      };
    }),
  };
}
