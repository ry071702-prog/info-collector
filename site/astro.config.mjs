import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "astro/config";

const rawBase = process.env.PUBLIC_BASE_PATH ?? "/";
const base = rawBase === "/" ? "/" : `/${rawBase.replace(/^\/|\/$/g, "")}`;

export default defineConfig({
  site: process.env.PUBLIC_SITE_URL ?? "https://example.github.io",
  base,
  vite: {
    plugins: [tailwindcss()],
  },
});
