import { defineConfig } from "@lingui/cli";

export default defineConfig({
  sourceLocale: "fr",
  locales: ["fr", "en"],
  format: "po",
  compileNamespace: "ts",
  catalogs: [
    {
      path: "<rootDir>/src/locales/{locale}/messages",
      include: ["src"],
    },
  ],
});