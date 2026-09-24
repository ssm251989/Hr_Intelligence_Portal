// TENANT-CONFIG: every export here is a client-specific value that, today, is still baked
// into the frontend build -- see docs/HRMS_COMPLETE_SPEC.txt Part 1, Step 4 ("frontend
// constants sweep") and Part 6 section 5 ("BRANDING / WHITE-LABEL"). Part 6 replaces this
// whole file: GET /api/me/bootstrap and public GET /api/v1/public/branding?host= return the
// real per-tenant values (logo, product name, colours, ...) and the MUI theme is built from
// that response at runtime, not from a static import like this one. Until then, this file
// is only a staging point -- every current call site of one of these values imports it from
// here instead of using the literal directly, so the eventual Part 6 rewire touches exactly
// one file's exports, not every component that happened to reference "CTD Techs" by hand.
//
// Deliberately NOT exhaustive: frontend/src/theme/tokens.ts's BRAND_BLUE and friends are
// already a single, generic, non-client-specific design-system palette (see their own
// comment) -- Part 6 makes theme creation itself tenant-driven, but there's no separate
// "CTD Techs" color literal scattered elsewhere in frontend/src to stage here today.

export const ORG_DISPLAY_NAME = "CTD Techs";
export const ORG_LOGO_MARK = "CTD";
export const CAREERS_SITE_TITLE = `${ORG_DISPLAY_NAME} Careers`;
