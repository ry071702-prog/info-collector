import { loadDigests } from "./articles";
import { toReiwaYear } from "./japaneseDate";

export type Edition = "AM" | "PM";

interface ParsedSlug {
  date: string;
  edition: Edition | null;
}

function parseSlug(slug: string): ParsedSlug {
  const match = slug.match(/^(\d{4}-\d{2}-\d{2})(?:-(AM|PM))?$/i);
  return {
    date: match?.[1] ?? slug.slice(0, 10),
    edition: (match?.[2]?.toUpperCase() as Edition | undefined) ?? null,
  };
}

export function getIssueNumber(slug: string, edition: Edition): number {
  const target = parseSlug(slug);
  return loadDigests()
    .filter((digest) => {
      const parsed = parseSlug(digest.slug);
      return parsed.edition === edition && parsed.date <= target.date;
    })
    .sort((a, b) => parseSlug(a.slug).date.localeCompare(parseSlug(b.slug).date))
    .length;
}

export function getPublicationMeta(slug: string): {
  name: string;
  issueNumber: number;
  edition: Edition;
  dateLabel: string;
} {
  const parsed = parseSlug(slug);
  const edition: Edition = parsed.edition ?? "AM";
  const date = new Date(`${parsed.date}T00:00:00+09:00`);
  const year = date.getFullYear();
  const month = date.getMonth() + 1;
  const day = date.getDate();

  return {
    name: "日刊 情報収集",
    issueNumber: getIssueNumber(slug, edition),
    edition,
    dateLabel: `${year}年(令和${toReiwaYear(year)}年) ${month}月${day}日`,
  };
}
