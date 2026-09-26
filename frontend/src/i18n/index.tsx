import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

import { en, type Bundle, type MessageKey } from "./en";
import { hi } from "./hi";
import { ta } from "./ta";

// Part 15 C: UI text in English, Hindi and Tamil (K-B2). The signed-in user's language comes
// from bootstrap (their own `org.locale` preference, else the company's); company renames
// (Settings -> Languages, bootstrap.custom_labels) win over the bundles. Pre-login pages use
// the language this browser last used.

export type Locale = "en" | "hi" | "ta";
export const LOCALES: { code: Locale; label: string }[] = [
  { code: "en", label: "English" },
  { code: "hi", label: "हिन्दी" },
  { code: "ta", label: "தமிழ்" },
];
// Per-module bundles (i18n/pages/*.ts, each exporting en/hi/ta) merge in here, so a module's
// pages add text without touching the shared files above.
type PageBundle = Partial<Record<Locale, Record<string, string>>>;
const PAGE_BUNDLES = Object.values(import.meta.glob("./pages/*.ts", { eager: true }) as Record<string, PageBundle>);
const merge = (locale: Locale, base: Bundle): Bundle =>
  Object.assign({}, ...PAGE_BUNDLES.map((m) => m[locale] ?? {}), base) as Bundle;
const BUNDLES: Record<Locale, Bundle> = { en: merge("en", en), hi: merge("hi", hi), ta: merge("ta", ta) };
const STORAGE_KEY = "hrms.locale";

export type Vars = Record<string, string | number>;
export type TFunction = (key: MessageKey | string, vars?: Vars) => string;

function normalise(locale: string | null | undefined): Locale {
  const base = (locale ?? "en").split("-")[0].toLowerCase();
  return base === "hi" || base === "ta" ? base : "en";
}

function readStored(): Locale {
  try {
    return normalise(localStorage.getItem(STORAGE_KEY));
  } catch {
    return "en";
  }
}

// Part 17.1: a key missing from every bundle must never reach the screen as "a.b.c" --
// show its last part as words ("people.employees.title" -> "Title") and warn in dev so
// `npm run i18n:check` catches it before a build.
function readable(key: string): string {
  if (import.meta.env.DEV) console.warn(`[i18n] missing text for "${key}"`);
  const last = key.split(".").pop() ?? key;
  const words = last.replace(/_one$/, "").replace(/[_-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : key;
}

function build(locale: Locale, overrides: Record<string, string>): TFunction {
  const bundle = BUNDLES[locale];
  const lookup = (key: string): string | undefined =>
    overrides[key] ?? (bundle as Record<string, string>)[key] ?? (BUNDLES.en as Record<string, string>)[key];
  return (key, vars) => {
    const count = vars?.count;
    let text = (count === 1 ? lookup(`${key}_one`) : undefined) ?? lookup(key) ?? readable(key);
    if (vars) {
      const n = (v: string | number) => (typeof v === "number" ? v.toLocaleString(locale === "en" ? "en-IN" : `${locale}-IN`) : v);
      text = text.replace(/\{(\w+)\}/g, (m, name: string) => (name in vars ? String(n(vars[name])) : m));
    }
    return text;
  };
}

// Module-level copy for code outside React (e.g. explainError) -- kept in step with the provider.
let current: { locale: Locale; t: TFunction } = { locale: readStored(), t: build(readStored(), {}) };
export const t: TFunction = (key, vars) => current.t(key, vars);
export function currentLocale(): Locale {
  return current.locale;
}

interface I18nValue {
  locale: Locale;
  t: TFunction;
  setLocale: (locale: string) => void;
  setOverrides: (overrides: Record<string, string> | undefined) => void;
}

const I18nContext = createContext<I18nValue>({ locale: "en", t, setLocale: () => undefined, setOverrides: () => undefined });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(readStored);
  const [overrides, setOverridesState] = useState<Record<string, string>>({});

  const setLocale = useCallback((next: string) => {
    const l = normalise(next);
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* per-visit only */
    }
    setLocaleState(l);
  }, []);
  const setOverrides = useCallback((next: Record<string, string> | undefined) => setOverridesState(next ?? {}), []);

  const value = useMemo<I18nValue>(() => {
    const fn = build(locale, overrides);
    current = { locale, t: fn };
    document.documentElement.lang = locale;
    return { locale, t: fn, setLocale, setOverrides };
  }, [locale, overrides, setLocale, setOverrides]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  return useContext(I18nContext);
}

export function useT(): TFunction {
  return useContext(I18nContext).t;
}

export type { MessageKey };
