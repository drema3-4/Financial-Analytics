export function parseLocalizedDecimal(value: string, locale: string): string | null {
  const parts = decimalParts(locale);
  let normalized = value.trim().replace(/[\s\u00a0\u202f]/gu, "");
  if (parts.group !== "" && parts.group !== parts.decimal) {
    normalized = normalized.split(parts.group).join("");
  }
  if (parts.decimal !== ".") {
    normalized = normalized.split(parts.decimal).join(".");
  }
  if (!/^-?\d+(?:\.\d+)?$/u.test(normalized)) {
    return null;
  }
  const negative = normalized.startsWith("-");
  const unsigned = negative ? normalized.slice(1) : normalized;
  const [integer = "", fraction] = unsigned.split(".");
  const canonicalInteger = integer.replace(/^0+(?=\d)/u, "") || "0";
  return `${negative ? "-" : ""}${canonicalInteger}${fraction === undefined ? "" : `.${fraction}`}`;
}

export function localDateAtNoonUtc(date: string, timezone: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/u.exec(date);
  if (match === null) {
    throw new Error("Date must use YYYY-MM-DD format");
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const target = Date.UTC(year, month - 1, day, 12, 0, 0);
  let candidate = target;
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });
  for (let iteration = 0; iteration < 2; iteration += 1) {
    const values = Object.fromEntries(
      formatter
        .formatToParts(new Date(candidate))
        .filter((part) => part.type !== "literal")
        .map((part) => [part.type, Number(part.value)]),
    );
    const observed = Date.UTC(
      values.year ?? 0,
      (values.month ?? 1) - 1,
      values.day ?? 1,
      values.hour ?? 0,
      values.minute ?? 0,
      values.second ?? 0,
    );
    candidate += target - observed;
  }
  return new Date(candidate).toISOString();
}

export function todayIsoDate(now = new Date()): string {
  const year = String(now.getFullYear()).padStart(4, "0");
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function isZeroDecimal(value: string): boolean {
  return /^-?0+(?:\.0+)?$/u.test(value);
}

export function decimalSeparator(locale: string): string {
  return decimalParts(locale).decimal;
}

function decimalParts(locale: string): { decimal: string; group: string } {
  try {
    const parts = new Intl.NumberFormat(locale).formatToParts(12345.6);
    return {
      decimal: parts.find((part) => part.type === "decimal")?.value ?? ".",
      group: parts.find((part) => part.type === "group")?.value ?? "",
    };
  } catch {
    return { decimal: ".", group: "," };
  }
}
