const WEEKDAYS = ["日", "月", "火", "水", "木", "金", "土"];

export function toReiwaYear(year: number): number {
  return year - 2018;
}

export function formatJapaneseDate(value: Date | string): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  const year = date.getFullYear();
  const reiwaYear = toReiwaYear(year);
  const weekday = WEEKDAYS[date.getDay()];
  return `${year}年(令和${reiwaYear}年) ${date.getMonth() + 1}月${date.getDate()}日(${weekday}曜日)`;
}
