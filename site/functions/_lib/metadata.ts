export interface PageMetadata {
  url: string;
  domain: string;
  title: string;
  description: string;
  image_url: string | null;
  favicon_url: string | null;
}

interface TextHandler {
  text(text: { text: string }): void;
}

interface ElementHandler {
  element(element: { getAttribute(name: string): string | null }): void;
}

declare const HTMLRewriter: {
  new(): HTMLRewriterInstance;
};

interface HTMLRewriterInstance {
  on(selector: string, handler: TextHandler | ElementHandler): HTMLRewriterInstance;
  transform(response: Response): Response;
}

function absoluteUrl(value: string | null, baseUrl: URL): string | null {
  if (!value) return null;
  try {
    return new URL(value, baseUrl).toString();
  } catch {
    return null;
  }
}

function cleanText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

export function normalizeHttpUrl(value: unknown): URL | null {
  if (typeof value !== "string" || value.trim().length === 0) return null;
  try {
    const parsed = new URL(value.trim());
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    return parsed;
  } catch {
    return null;
  }
}

export async function fetchPageMetadata(url: URL): Promise<PageMetadata> {
  const collected = {
    titleText: "",
    ogTitle: "",
    ogDescription: "",
    ogImage: "",
    favicon: "",
  };

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(url.toString(), {
      headers: {
        Accept: "text/html,application/xhtml+xml",
        "User-Agent": "info-collector-savebot/1.0",
      },
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`metadata fetch failed: ${response.status}`);
    }

    const rewriter = new HTMLRewriter()
      .on("title", {
        text(text) {
          collected.titleText += text.text;
        },
      })
      .on("meta[property='og:title'], meta[name='twitter:title']", {
        element(element) {
          collected.ogTitle ||= element.getAttribute("content") ?? "";
        },
      })
      .on("meta[property='og:description'], meta[name='description'], meta[name='twitter:description']", {
        element(element) {
          collected.ogDescription ||= element.getAttribute("content") ?? "";
        },
      })
      .on("meta[property='og:image'], meta[name='twitter:image']", {
        element(element) {
          collected.ogImage ||= element.getAttribute("content") ?? "";
        },
      })
      .on("link[rel='icon'], link[rel='shortcut icon'], link[rel='apple-touch-icon']", {
        element(element) {
          collected.favicon ||= element.getAttribute("href") ?? "";
        },
      });

    await rewriter.transform(response).arrayBuffer();
  } finally {
    clearTimeout(timeoutId);
  }

  return {
    url: url.toString(),
    domain: url.hostname,
    title: cleanText(collected.ogTitle || collected.titleText || url.toString()),
    description: cleanText(collected.ogDescription),
    image_url: absoluteUrl(collected.ogImage, url),
    favicon_url: absoluteUrl(collected.favicon || "/favicon.ico", url),
  };
}
