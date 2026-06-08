import {
  genreColors,
  genreLabels,
  genres,
  loadSiteData,
  sortArticlesByTimestamp,
  type Article,
  type Genre,
  type Priority,
} from "./articles";

export interface CountEntry {
  key: string;
  label: string;
  count: number;
  percentage: number;
}

export interface TagEntry extends CountEntry {
  tag: string;
  slug: string;
}

export interface GenreCount extends CountEntry {
  genre: Genre;
  color: string;
}

export interface PriorityCount extends CountEntry {
  priority: Priority;
}

export interface DailyCount {
  date: string;
  label: string;
  total: number;
  genres: Record<Genre, number>;
}

export interface RisingTag extends TagEntry {
  previousCount: number;
  delta: number;
  lift: number;
}

export interface SiteStats {
  totalArticles: number;
  todayArticles: number;
  weekArticles: number;
  genreCounts: GenreCount[];
  priorityCounts: PriorityCount[];
  topTags: TagEntry[];
  topSources: CountEntry[];
  dailyCounts: DailyCount[];
  risingTags: RisingTag[];
  lastUpdated: Date | null;
  lastUpdatedLabel: string;
  referenceDate: Date;
}

export const MIN_TAG_PAGE_COUNT = 3;

const priorities: Priority[] = ["S", "A", "B", "C"];
const jstDateFormatter = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});
const jstDateTimeFormatter = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});
const jstShortDateFormatter = new Intl.DateTimeFormat("ja-JP", {
  timeZone: "Asia/Tokyo",
  month: "numeric",
  day: "numeric",
});

function validDate(value?: string): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function jstDayKey(date: Date): string {
  return jstDateFormatter.format(date).replaceAll("/", "-");
}

export function startOfJstDay(date: Date): Date {
  return new Date(`${jstDayKey(date)}T00:00:00+09:00`);
}

function addDays(date: Date, days: number): Date {
  const next = new Date(date);
  next.setUTCDate(next.getUTCDate() + days);
  return next;
}

function labelForDate(date: Date): string {
  return jstShortDateFormatter.format(date);
}

function referenceDateFor(articles: Article[], generatedAt?: string): Date {
  const generatedDate = validDate(generatedAt);
  if (generatedDate) return generatedDate;
  const latestArticle = articles
    .map((article) => validDate(article.timestamp))
    .filter((date): date is Date => date !== null)
    .sort((a, b) => b.getTime() - a.getTime())[0];
  return latestArticle ?? new Date();
}

function tagKey(tag: string): string {
  return tag.trim().toLowerCase();
}

function articleTags(article: Article): string[] {
  return Array.from(new Set([...article.title_tags, ...article.entity_tags].map((tag) => tag.trim()).filter(Boolean)));
}

function increment(map: Map<string, { label: string; count: number }>, key: string, label: string): void {
  const current = map.get(key);
  map.set(key, { label: current?.label ?? label, count: (current?.count ?? 0) + 1 });
}

function rankedEntries(map: Map<string, { label: string; count: number }>, total: number, limit?: number): CountEntry[] {
  const denominator = Math.max(1, total);
  const entries = [...map.entries()]
    .map(([key, value]) => ({
      key,
      label: value.label,
      count: value.count,
      percentage: (value.count / denominator) * 100,
    }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label, "ja"));
  return typeof limit === "number" ? entries.slice(0, limit) : entries;
}

export function tagPathSegment(tag: string): string {
  const encoded = encodeURIComponent(tag).replaceAll("%", "~");
  if (encoded.length <= 96) {
    return encoded;
  }
  let hash = 2166136261;
  for (let index = 0; index < tag.length; index += 1) {
    hash ^= tag.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `t-${(hash >>> 0).toString(36)}`;
}

export function allTagEntries(articles: Article[]): TagEntry[] {
  const tagCounts = new Map<string, { label: string; count: number }>();
  for (const article of articles) {
    for (const tag of articleTags(article)) {
      increment(tagCounts, tagKey(tag), tag);
    }
  }
  return rankedEntries(tagCounts, articles.length).map((entry) => ({
    ...entry,
    tag: entry.label,
    slug: tagPathSegment(entry.label),
  }));
}

export function tagPageEntries(articles: Article[], minCount = MIN_TAG_PAGE_COUNT): TagEntry[] {
  return allTagEntries(articles).filter((tag) => tag.count >= minCount);
}

let cachedTagPageKeys: Set<string> | null = null;

export function hasTagPage(tag: string, articles?: Article[], minCount = MIN_TAG_PAGE_COUNT): boolean {
  const key = tagKey(tag);
  if (!key) return false;
  if (articles) {
    return tagPageEntries(articles, minCount).some((entry) => entry.key === key);
  }
  if (!cachedTagPageKeys) {
    cachedTagPageKeys = new Set(tagPageEntries(loadSiteData().articles, minCount).map((entry) => entry.key));
  }
  return cachedTagPageKeys.has(key);
}

export function articlesForTag(articles: Article[], tag: string): Article[] {
  const key = tagKey(tag);
  return sortArticlesByTimestamp(articles.filter((article) => articleTags(article).some((item) => tagKey(item) === key)));
}

export function dailyCounts(articles: Article[], days = 14, referenceDate = referenceDateFor(articles)): DailyCount[] {
  const todayStart = startOfJstDay(referenceDate);
  const windowStart = addDays(todayStart, -(days - 1));
  const counts = new Map<string, DailyCount>();

  for (let index = 0; index < days; index += 1) {
    const date = addDays(windowStart, index);
    counts.set(jstDayKey(date), {
      date: jstDayKey(date),
      label: labelForDate(date),
      total: 0,
      genres: { games: 0, anime: 0, disney: 0 },
    });
  }

  for (const article of articles) {
    const timestamp = validDate(article.timestamp);
    if (!timestamp || timestamp < windowStart || timestamp > referenceDate) continue;
    const key = jstDayKey(timestamp);
    const entry = counts.get(key);
    if (!entry) continue;
    entry.total += 1;
    entry.genres[article.genre] = (entry.genres[article.genre] ?? 0) + 1;
  }

  return [...counts.values()];
}

export function risingTags(articles: Article[], limit = 10, recentDays = 7, previousDays = 7, referenceDate = referenceDateFor(articles)): RisingTag[] {
  const todayStart = startOfJstDay(referenceDate);
  const recentStart = addDays(todayStart, -(recentDays - 1));
  const previousStart = addDays(recentStart, -previousDays);
  const recent = new Map<string, { label: string; count: number }>();
  const previous = new Map<string, { label: string; count: number }>();

  for (const article of articles) {
    const timestamp = validDate(article.timestamp);
    if (!timestamp || timestamp > referenceDate || timestamp < previousStart) continue;
    const target = timestamp >= recentStart ? recent : previous;
    for (const tag of articleTags(article)) {
      increment(target, tag.toLowerCase(), tag);
    }
  }

  return [...recent.entries()]
    .map(([key, value]) => {
      const previousCount = previous.get(key)?.count ?? 0;
      const delta = value.count - previousCount;
      const lift = value.count / Math.max(1, previousCount);
      return {
        key,
        label: value.label,
        tag: value.label,
        slug: tagPathSegment(value.label),
        count: value.count,
        previousCount,
        delta,
        lift,
        percentage: 0,
      };
    })
    .filter((entry) => entry.delta > 0)
    .sort((a, b) => b.delta - a.delta || b.lift - a.lift || b.count - a.count || a.label.localeCompare(b.label, "ja"))
    .slice(0, limit);
}

export function buildSiteStats(articles: Article[], generatedAt?: string, options: { tagLimit?: number; sourceLimit?: number; dailyDays?: number } = {}): SiteStats {
  const referenceDate = referenceDateFor(articles, generatedAt);
  const todayStart = startOfJstDay(referenceDate);
  const weekStart = addDays(todayStart, -6);
  const lastUpdated =
    validDate(generatedAt) ??
    articles
      .map((article) => validDate(article.timestamp))
      .filter((date): date is Date => date !== null)
      .sort((a, b) => b.getTime() - a.getTime())[0] ??
    null;

  const genreMap = new Map<Genre, number>(genres.map((genre) => [genre, 0]));
  const priorityMap = new Map<Priority, number>(priorities.map((priority) => [priority, 0]));
  const sourceMap = new Map<string, { label: string; count: number }>();
  let todayArticles = 0;
  let weekArticles = 0;

  for (const article of articles) {
    const timestamp = validDate(article.timestamp);
    if (timestamp && timestamp >= todayStart && timestamp <= referenceDate) todayArticles += 1;
    if (timestamp && timestamp >= weekStart && timestamp <= referenceDate) weekArticles += 1;

    genreMap.set(article.genre, (genreMap.get(article.genre) ?? 0) + 1);
    priorityMap.set(article.final_priority, (priorityMap.get(article.final_priority) ?? 0) + 1);

    const sourceLabel = article.domain || article.source_platform || article.author || article.source_id || "unknown";
    const sourceKey = sourceLabel.trim().toLowerCase().replace(/[,\s]+/g, "-");
    increment(sourceMap, sourceKey, sourceLabel);
  }

  const total = articles.length;
  const maxGenre = Math.max(1, ...genreMap.values());
  const maxPriority = Math.max(1, ...priorityMap.values());

  return {
    totalArticles: total,
    todayArticles,
    weekArticles,
    genreCounts: genres.map((genre) => {
      const count = genreMap.get(genre) ?? 0;
      return {
        key: genre,
        genre,
        label: genreLabels[genre],
        count,
        color: genreColors[genre],
        percentage: (count / maxGenre) * 100,
      };
    }),
    priorityCounts: priorities.map((priority) => {
      const count = priorityMap.get(priority) ?? 0;
      return {
        key: priority.toLowerCase(),
        priority,
        label: priority,
        count,
        percentage: (count / maxPriority) * 100,
      };
    }),
    topTags: allTagEntries(articles).slice(0, options.tagLimit ?? 10),
    topSources: rankedEntries(sourceMap, total, options.sourceLimit ?? 10),
    dailyCounts: dailyCounts(articles, options.dailyDays ?? 14, referenceDate),
    risingTags: risingTags(articles, 10, 7, 7, referenceDate),
    lastUpdated,
    lastUpdatedLabel: lastUpdated ? `${jstDateTimeFormatter.format(lastUpdated).replaceAll("/", "-")} JST` : "未生成",
    referenceDate,
  };
}

export function loadSiteStats(options: { tagLimit?: number; sourceLimit?: number; dailyDays?: number } = {}): SiteStats {
  const siteData = loadSiteData();
  return buildSiteStats(siteData.articles, siteData.generated_at, options);
}
