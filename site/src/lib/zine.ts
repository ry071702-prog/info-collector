import type { Article } from "./articles";

// 相対時刻（ビルド時点基準・静的サイトなので publish 毎に再計算される）
export function ago(ts: string): string {
  const diff = Date.now() - new Date(ts).getTime();
  const min = Math.max(1, Math.round(diff / 60000));
  if (min < 60) return `${min}分前`;
  const hours = Math.round(min / 60);
  if (hours < 24) return `${hours}時間前`;
  return `${Math.round(hours / 24)}日前`;
}

function firstSentence(s: string): string {
  const t = (s || "").trim();
  const m = t.match(/^[\s\S]{8,58}?。/);
  return (m ? m[0] : t.slice(0, 52)).replace(/。$/, "");
}

// category_name は分類ラベルで重複しがちなので、要約の第1文をヘッドラインにする
export function headline(a: Article): string {
  const s = (a.summary || "").trim();
  if (s.length > 8) return firstSentence(s);
  return a.category_name && a.category_name !== "ニュース" ? a.category_name : (a.title_tags[0] || "最新トピック");
}

export function detail(a: Article): string {
  const s = (a.summary || "").trim();
  const head = firstSentence(s);
  return s.slice(head.length).replace(/^。/, "").trim();
}

export function kicker(a: Article): string {
  return a.category_name && a.category_name !== "ニュース" ? a.category_name : "";
}
