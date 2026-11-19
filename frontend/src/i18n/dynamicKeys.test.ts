import { describe, expect, it } from "vitest";

import { en } from "./en";
import { hi } from "./hi";
import { ta } from "./ta";
import { CATEGORIES } from "../settings/catalog";

// ST2 (Part 27): keys built at run time (`settingsHome.page.${cat}.${page}`) are invisible to `npm run i18n:check`
// (a static scan) - 10 were missing and showed console warnings. This test builds them from the catalog.
type Bundle = Record<string, string>;
const pages = Object.values(import.meta.glob("./pages/*.ts", { eager: true }) as Record<string, Partial<Record<"en" | "hi" | "ta", Bundle>>>);
const all = (locale: "en" | "hi" | "ta", base: Bundle) => Object.assign({}, ...pages.map((m) => m[locale] ?? {}), base) as Bundle;
const BUNDLES = { en: all("en", en as Bundle), hi: all("hi", hi as Bundle), ta: all("ta", ta as Bundle) };

describe("dynamic UI text keys", () => {
  it("every Settings category and page has a name in English, Hindi and Tamil", () => {
    const keys = CATEGORIES.flatMap((c) => [`settingsHome.cat.${c.id}`, ...c.pages.map((p) => `settingsHome.page.${c.id}.${p.id}`)]);
    for (const locale of ["en", "hi", "ta"] as const) {
      expect(keys.filter((k) => !BUNDLES[locale][k]), locale).toEqual([]);
    }
  });
});
