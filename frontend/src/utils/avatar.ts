/** Initials for an avatar badge from a name (or email fallback) -- e.g. "Jane Doe" -> "JD",
 * "jane@example.com" -> "JA". Never a stock photo, consistent with this app's
 * real-data-only principle (see layout/AppLayout.tsx's own copy of this same logic for the
 * signed-in user's avatar). */
export function initials(nameOrEmail: string): string {
  const trimmed = nameOrEmail.trim();
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return trimmed.slice(0, 2).toUpperCase();
}
