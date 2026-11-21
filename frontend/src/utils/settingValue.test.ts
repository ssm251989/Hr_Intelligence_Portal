import { describe, expect, it } from "vitest";

import { parseEditValue, valueToEditString } from "./settingValue";

describe("parseEditValue", () => {
  it("parses whole numbers", () => {
    expect(parseEditValue("75", "int")).toBe(75);
    expect(parseEditValue(" -3 ", "int")).toBe(-3);
  });

  it.each(["", "  ", "abc", "7.5", "1e3", "12abc"])("rejects %j for a whole-number setting instead of sending null", (raw) => {
    expect(() => parseEditValue(raw, "int")).toThrow();
  });

  it("parses decimals and rejects junk", () => {
    expect(parseEditValue("0.75", "decimal")).toBe(0.75);
    expect(parseEditValue("2", "decimal")).toBe(2);
    expect(() => parseEditValue("", "decimal")).toThrow();
    expect(() => parseEditValue("abc", "decimal")).toThrow();
  });

  it("keeps text and booleans as they are", () => {
    expect(parseEditValue("Asia/Kolkata", "str")).toBe("Asia/Kolkata");
    expect(parseEditValue("true", "bool")).toBe(true);
    expect(parseEditValue("false", "bool")).toBe(false);
  });

  it("parses JSON and gives a readable error for bad JSON", () => {
    expect(parseEditValue("[24, 48]", "json")).toEqual([24, 48]);
    expect(() => parseEditValue("[24,", "json")).toThrow(/JSON/);
  });
});

describe("clearing a JSON setting (Part 31)", () => {
  it("an empty box gives the built-in default instead of a JSON error", () => {
    expect(parseEditValue("", "json", [24, 48])).toEqual([24, 48]);
    expect(parseEditValue("   ", "json", { a: 1 })).toEqual({ a: 1 });
  });

  it("an empty box gives null when the default is null", () => {
    expect(parseEditValue("", "json", null)).toBeNull();
    expect(parseEditValue("", "json")).toBeNull();
  });

  it("numbers still refuse an empty box", () => {
    expect(() => parseEditValue("", "int", 75)).toThrow();
  });
});

describe("valueToEditString", () => {
  it("round-trips through parseEditValue", () => {
    expect(valueToEditString(null)).toBe("");
    expect(valueToEditString("x")).toBe("x");
    expect(parseEditValue(valueToEditString([1, 2]), "json")).toEqual([1, 2]);
    expect(parseEditValue(valueToEditString(42), "int")).toBe(42);
  });
});
