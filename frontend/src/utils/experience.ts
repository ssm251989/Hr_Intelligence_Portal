// Shared by every place a job's experience_min_years/experience_max_years is displayed
// (Jobs List CSV export, Job Details dialog, Careers list/detail pages) -- one formatter
// so "3-5 yrs" / "5+ yrs" never gets rendered slightly differently in two places.
export function formatExperienceRange(
  minYears?: number | null,
  maxYears?: number | null,
): string | null {
  if (minYears == null && maxYears == null) return null;
  if (maxYears == null) return `${minYears}+ yrs`;
  if (minYears == null) return `Up to ${maxYears} yrs`;
  if (minYears === maxYears) return `${minYears} yrs`;
  return `${minYears}-${maxYears} yrs`;
}
