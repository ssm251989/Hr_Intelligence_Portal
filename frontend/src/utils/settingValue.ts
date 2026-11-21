import { t } from "../i18n";

// Turning a raw setting value into the text shown in the edit box, and back again.

export function valueToEditString(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

/** Throws an Error with a user-facing message when `raw` isn't a valid value for `type` --
 * never returns NaN/null for a number (that used to be saved as null and break the server).
 * Part 31: an empty box for a JSON-shaped setting means "clear it" -> `emptyValue` (the setting's built-in default,
 * which is null when the default is null), never "not valid JSON". */
export function parseEditValue(raw: string, type: string, emptyValue: unknown = null): unknown {
  const text = raw.trim();
  if (type === "int") {
    if (!/^-?\d+$/.test(text)) throw new Error(t("settings.invalid_whole_number"));
    return Number(text);
  }
  if (type === "decimal") {
    const n = Number(text);
    if (text === "" || !Number.isFinite(n)) throw new Error(t("settings.invalid_number"));
    return n;
  }
  if (type === "bool") return raw === "true";
  if (type === "str" || type === "enum" || type === "color" || type === "email" || type === "url") return raw;
  if (text === "") return emptyValue;
  try {
    return JSON.parse(raw); // json, duration, time, and everything else: raw JSON text
  } catch {
    throw new Error(t("settings.invalid_json"));
  }
}
