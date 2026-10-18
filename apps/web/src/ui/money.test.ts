import { describe, expect, it } from "vitest";

import {
  isZeroDecimal,
  localDateAtNoonUtc,
  operationInstant,
  parseLocalizedDecimal,
  todayIsoDate,
} from "./money";

describe("decimal string controls", () => {
  it("normalizes locale punctuation without using binary floating point", () => {
    expect(parseLocalizedDecimal("9 007 199 254 740 993,123456789", "ru-RU")).toBe(
      "9007199254740993.123456789",
    );
    expect(parseLocalizedDecimal("1,234,567.89", "en-US")).toBe("1234567.89");
    expect(parseLocalizedDecimal("001.20", "en-US")).toBe("1.20");
    expect(parseLocalizedDecimal("-000,50", "ru-RU")).toBe("-0.50");
    expect(parseLocalizedDecimal("1,234.50", "not_a_locale")).toBe("1234.50");
  });

  it("rejects exponent and ambiguous decimal syntax", () => {
    expect(parseLocalizedDecimal("1e6", "ru-RU")).toBeNull();
    expect(parseLocalizedDecimal("12,3,4", "ru-RU")).toBeNull();
    expect(parseLocalizedDecimal("", "ru-RU")).toBeNull();
  });

  it("recognizes decimal zero without conversion", () => {
    expect(isZeroDecimal("-0.000")).toBe(true);
    expect(isZeroDecimal("0.01")).toBe(false);
  });

  it("converts local noon in an explicit timezone to a UTC instant", () => {
    expect(localDateAtNoonUtc("2026-10-14", "Europe/Saratov")).toBe("2026-10-14T08:00:00.000Z");
    expect(() => localDateAtNoonUtc("14.10.2026", "Europe/Saratov")).toThrow("YYYY-MM-DD");
  });
  it("uses the profile timezone for dates near midnight", () => {
    const instant = new Date("2026-10-17T21:30:00Z");
    expect(todayIsoDate(instant, "Europe/Saratov")).toBe("2026-10-18");
    expect(todayIsoDate(instant, "America/New_York")).toBe("2026-10-17");
  });
  it("records today's operation now instead of creating a future noon posting", () => {
    const morning = new Date("2026-10-19T01:30:00Z");
    expect(operationInstant("2026-10-19", "Europe/Saratov", morning)).toBe(
      "2026-10-19T01:30:00.000Z",
    );
    expect(operationInstant("2026-10-18", "Europe/Saratov", morning)).toBe(
      "2026-10-18T08:00:00.000Z",
    );
  });
});
