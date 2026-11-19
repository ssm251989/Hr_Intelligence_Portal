// J2 (Part 27): ONE money format everywhere - rupee sign + Indian digit grouping ("₹14,00,000"), and "8 L" for
// lakhs in compact places. Pages used raw numbers ("Pay 800000 - 1500000") next to "₹14,00,000" elsewhere.
export function formatMoney(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? `₹${Math.round(n).toLocaleString("en-IN")}` : "—";
}

export function formatLakh(v: number | string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? `${(n / 100000).toLocaleString("en-IN", { maximumFractionDigits: 1 })} L` : "—";
}
