-- Phase 0 需要計測用テーブル（waitlist / フェイクドア登録）
-- 適用: wrangler pages / d1 で以下を実行する
--   npx wrangler d1 execute info-collector-saves --remote --file=./schema/waitlist.sql
--   ローカル: npx wrangler d1 execute info-collector-saves --local --file=./schema/waitlist.sql
-- 既存の saved_items と同じ D1 (binding DB / info-collector-saves) に同居させる。

CREATE TABLE IF NOT EXISTS waitlist (
  id          TEXT PRIMARY KEY,
  email       TEXT NOT NULL UNIQUE,
  genres      TEXT NOT NULL,          -- 選択ジャンル slug の JSON 配列
  genre_count INTEGER NOT NULL DEFAULT 0,
  country     TEXT,                   -- Cloudflare の request.cf.country（任意）
  referrer    TEXT,                   -- 流入元（任意・計測用）
  user_agent  TEXT,
  created_at  TEXT NOT NULL,
  updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_waitlist_created_at ON waitlist (created_at);
