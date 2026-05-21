import { existsSync, readFileSync } from "node:fs";
import { basename, join, resolve } from "node:path";

export type Genre = "games" | "anime" | "disney";
export type Priority = "S" | "A" | "B" | "C";

export interface ArticleFlags {
  speed: string;
  spoiler: string;
  source_reliability: string;
}

export interface Article {
  url: string;
  source_id?: string;
  source_platform?: string;
  author: string;
  timestamp: string;
  genre: Genre;
  subcategory_id: string;
  category_name: string;
  final_priority: Priority;
  summary: string;
  title_tags: string[];
  entity_tags: string[];
  flags: ArticleFlags;
  image_url: string | null;
  favicon_url: string | null;
  domain: string;
}

export interface Digest {
  date: string;
  slug: string;
  label: string;
}

interface SiteData {
  generated_at?: string;
  window_12h_count?: number;
  articles: Article[];
  digests: Digest[];
}

export const genres: Genre[] = ["games", "anime", "disney"];

export const genreLabels: Record<Genre, string> = {
  games: "ゲーム",
  anime: "アニメ",
  disney: "Disney",
};

export const genreColors: Record<Genre, string> = {
  games: "#2563eb",
  anime: "#db2777",
  disney: "#7c3aed",
};

const priorityOrder: Record<Priority, number> = {
  S: 0,
  A: 1,
  B: 2,
  C: 3,
};

function dataPath(): string {
  return join(process.cwd(), "src", "data", "articles.json");
}

export function loadSiteData(): SiteData {
  const path = dataPath();
  if (!existsSync(path)) {
    return { articles: [], digests: [] };
  }

  try {
    const parsed = JSON.parse(readFileSync(path, "utf-8")) as SiteData;
    return {
      generated_at: parsed.generated_at,
      window_12h_count: Number.isFinite(parsed.window_12h_count) ? parsed.window_12h_count : 0,
      articles: Array.isArray(parsed.articles) ? parsed.articles : [],
      digests: Array.isArray(parsed.digests) ? parsed.digests : [],
    };
  } catch (error) {
    console.warn(`Failed to load ${path}:`, error);
    return { articles: [], digests: [] };
  }
}

export function sortArticles(articles: Article[]): Article[] {
  return [...articles].sort((a, b) => {
    const priorityDiff = priorityOrder[a.final_priority] - priorityOrder[b.final_priority];
    if (priorityDiff !== 0) {
      return priorityDiff;
    }
    return new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime();
  });
}

export function sortArticlesByTimestamp(articles: Article[]): Article[] {
  return [...articles].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
}

export function byImportance(articles: Article[]): Article[] {
  return sortArticles(articles);
}

export function articlesByGenre(genre: Genre): Article[] {
  return sortArticlesByTimestamp(loadSiteData().articles.filter((article) => article.genre === genre));
}

export function allArticles(): Article[] {
  return sortArticlesByTimestamp(loadSiteData().articles);
}

export function latestArticles(limit: number): Article[] {
  return sortArticlesByTimestamp(loadSiteData().articles).slice(0, limit);
}

export function latestByGenre(genre: Genre, limit: number): Article[] {
  return sortArticlesByTimestamp(loadSiteData().articles.filter((article) => article.genre === genre)).slice(0, limit);
}

export function sourceKey(article: Pick<Article, "source_id" | "author" | "domain" | "source_platform">): string {
  const value = article.source_id || article.author || article.domain || article.source_platform || "unknown";
  return value.trim().toLowerCase().replace(/[,\s]+/g, "-");
}

export function sourceLabel(article: Pick<Article, "source_id" | "author" | "domain" | "source_platform">): string {
  return article.author || article.source_id || article.domain || article.source_platform || "unknown";
}

export function loadDigests(): Digest[] {
  return loadSiteData().digests;
}

export interface DigestDocument {
  date: string;
  title: string;
  html: string;
  excerpt: string;
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function inlineMarkdown(value: string): string {
  return escapeHtml(value)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
}

function markdownToHtml(markdown: string): string {
  const lines = markdown.split(/\r?\n/);
  const html: string[] = [];
  let inList = false;

  for (const line of lines) {
    if (line.startsWith("# ")) {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      html.push(`<h1>${inlineMarkdown(line.slice(2).trim())}</h1>`);
    } else if (line.startsWith("## ")) {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      html.push(`<h2>${inlineMarkdown(line.slice(3).trim())}</h2>`);
    } else if (line.startsWith("### ")) {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      html.push(`<h3>${inlineMarkdown(line.slice(4).trim())}</h3>`);
    } else if (line.startsWith("- ")) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(line.slice(2).trim())}</li>`);
    } else if (line.trim() === "") {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
    } else {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
      html.push(`<p>${inlineMarkdown(line.trim())}</p>`);
    }
  }

  if (inList) {
    html.push("</ul>");
  }
  return html.join("\n");
}

export function loadDigestDocument(slug: string): DigestDocument | null {
  const digestPath = resolve(process.cwd(), "..", "docs", "digests", `${basename(slug)}.md`);
  if (!existsSync(digestPath)) {
    return null;
  }

  const markdown = readFileSync(digestPath, "utf-8");
  const plainLines = markdown
    .split(/\r?\n/)
    .map((line) => line.replace(/^#+\s*/, "").trim())
    .filter(Boolean);
  return {
    date: slug,
    title: plainLines[0] ?? `Digest ${slug}`,
    html: markdownToHtml(markdown),
    excerpt: plainLines.slice(1, 3).join(" ").slice(0, 140),
  };
}
