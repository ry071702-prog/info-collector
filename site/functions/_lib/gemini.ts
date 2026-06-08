import type { SavedItem } from "./types";

export const GEMINI_MODEL = "gemini-flash-latest";

export interface GeminiSummary {
  summary: string;
  tags: string[];
  category: string;
  importance: SavedItem["importance"];
}

const validImportance = new Set(["S", "A", "B", "C"]);

function normalizeSummary(value: unknown): GeminiSummary | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const summary = typeof record.summary === "string" ? record.summary.trim() : "";
  const tags = Array.isArray(record.tags)
    ? record.tags
        .map((tag) => String(tag).trim())
        .filter(Boolean)
        .slice(0, 5)
    : [];
  const category = typeof record.category === "string" && record.category.trim() ? record.category.trim() : "other";
  const importance = typeof record.importance === "string" && validImportance.has(record.importance.toUpperCase())
    ? (record.importance.toUpperCase() as SavedItem["importance"])
    : "C";
  return { summary, tags, category, importance };
}

function parseGeminiJson(text: string): GeminiSummary | null {
  const trimmed = text.trim().replace(/^```json\s*/i, "").replace(/^```\s*/i, "").replace(/```$/i, "").trim();
  try {
    return normalizeSummary(JSON.parse(trimmed));
  } catch {
    const match = trimmed.match(/\{[\s\S]*\}/);
    if (!match) return null;
    try {
      return normalizeSummary(JSON.parse(match[0]));
    } catch {
      return null;
    }
  }
}

export async function summarizeWithGemini(input: {
  apiKey: string;
  title: string;
  description: string;
  note: string;
  domain: string;
}): Promise<GeminiSummary | null> {
  if (!input.apiKey) return null;

  const prompt = [
    "あなたは個人用ニュースコレクションの整理係です。",
    "以下の保存対象を日本語で整理し、JSONだけを返してください。",
    "schema: {\"summary\":\"3行以内の要約\",\"tags\":[\"最大5件\"],\"category\":\"games|anime|disney|tech|other など短い分類\",\"importance\":\"S|A|B|C\"}",
    "importance は S=今すぐ読むべき重要情報、A=重要、B=通常、C=低優先です。",
    "",
    `domain: ${input.domain}`,
    `title: ${input.title}`,
    `description: ${input.description}`,
    `note: ${input.note}`,
  ].join("\n");

  try {
    const response = await fetch(`https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${encodeURIComponent(input.apiKey)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{ parts: [{ text: prompt }] }],
        generationConfig: {
          responseMimeType: "application/json",
          temperature: 0.2,
        },
      }),
    });

    if (!response.ok) {
      console.warn("Gemini request failed", response.status);
      return null;
    }
    const data = (await response.json()) as Record<string, unknown>;
    const candidates = Array.isArray(data.candidates) ? data.candidates : [];
    const first = candidates[0] as Record<string, unknown> | undefined;
    const content = first?.content as Record<string, unknown> | undefined;
    const parts = Array.isArray(content?.parts) ? content.parts : [];
    const text = parts
      .map((part) => (part && typeof part === "object" && "text" in part ? String((part as { text: unknown }).text) : ""))
      .join("\n");
    return text ? parseGeminiJson(text) : null;
  } catch (error) {
    console.warn("Gemini summarization skipped", error);
    return null;
  }
}
