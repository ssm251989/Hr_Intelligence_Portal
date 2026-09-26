import type { NavEntry } from "../api/client";

// Part 15 app shell: the menu comes from GET /api/me/bootstrap (module registry x enablement x
// permissions, each entry carrying its sidebar group and emoji name). This static list is
// only what shows until bootstrap loads (or if it fails), so the app is never menu-less.

export type NavGroup = NonNullable<NavEntry["group"]>;

export const NAV_GROUP_ORDER: NavGroup[] = ["today", "hiring", "people", "insights", "admin"];

export const NAV_GROUP_LABELS: Record<NavGroup, string> = {
  today: "Today", hiring: "Hiring", people: "People", insights: "Insights", admin: "Admin",
};

export const NAV_LABELS: Record<string, string> = {
  "nav.overview": "Home", "nav.approvals": "My approvals", "nav.jobs": "Jobs", "nav.candidates": "Candidates",
  "nav.screening": "Screening", "nav.shortlisting": "Shortlisting", "nav.interviews": "Interviews", "nav.hr_inbox": "HR Inbox",
  "nav.salary": "Salary", "nav.bgv": "Background checks", "nav.offers": "Offers", "nav.reports": "Reports",
  "nav.onboarding": "Onboarding", "nav.employees": "Employees", "nav.performance": "Performance", "nav.helpdesk": "Helpdesk",
  "nav.assets": "Assets", "nav.exits": "Exits", "nav.analytics": "Analytics", "nav.setup": "Setup checklist", "nav.settings": "Settings",
};

export const FALLBACK_NAV: NavEntry[] = [
  { label_key: "nav.overview", path: "/", group: "today", icon: "house" },
  { label_key: "nav.approvals", path: "/approvals", group: "today", icon: "check" },
  { label_key: "nav.jobs", path: "/jobs", group: "hiring", icon: "briefcase" },
  { label_key: "nav.candidates", path: "/candidates/dashboard", group: "hiring", icon: "technologist" },
  { label_key: "nav.screening", path: "/screening/dashboard", group: "hiring", icon: "magnifier" },
  { label_key: "nav.shortlisting", path: "/shortlisting/dashboard", group: "hiring", icon: "star" },
  { label_key: "nav.interviews", path: "/interviews/dashboard", group: "hiring", icon: "calendar" },
  { label_key: "nav.hr_inbox", path: "/hr-inbox", group: "hiring", icon: "inbox" },
  { label_key: "nav.salary", path: "/salary", group: "hiring", icon: "money" },
  { label_key: "nav.bgv", path: "/bgv", group: "hiring", icon: "shield" },
  { label_key: "nav.offers", path: "/offers", group: "hiring", icon: "envelope" },
  { label_key: "nav.reports", path: "/reports", group: "insights", icon: "bar_chart" },
  { label_key: "nav.settings", path: "/settings", group: "admin", icon: "gear" },
];

// Sub-pages shown under a menu item (keyed by the section's path prefix).
export const NAV_CHILDREN: Record<string, { label: string; path: string }[]> = {
  "/candidates": [
    { label: "Dashboard", path: "/candidates/dashboard" },
    { label: "All candidates", path: "/candidates/list" },
    { label: "Import", path: "/candidates/import" },
  ],
  "/screening": [
    { label: "Dashboard", path: "/screening/dashboard" },
    { label: "Screening list", path: "/screening/list" },
  ],
  "/shortlisting": [
    { label: "Dashboard", path: "/shortlisting/dashboard" },
    { label: "Shortlist", path: "/shortlisting/list" },
  ],
  "/interviews": [
    { label: "Dashboard", path: "/interviews/dashboard" },
    { label: "All interviews", path: "/interviews/list" },
  ],
};

export function sectionOf(path: string): string {
  const clean = path.split("#")[0];
  const first = clean.split("/").filter(Boolean)[0];
  return first ? `/${first}` : "/";
}

// Bell groups (L-H5): module -> label + emoji name.
export const NOTIFICATION_MODULES: Record<string, { label: string; icon: string }> = {
  hiring: { label: "Hiring", icon: "briefcase" },
  approvals: { label: "Approvals", icon: "check" },
  onboarding: { label: "Onboarding", icon: "waving_hand" },
  people: { label: "People", icon: "people" },
  performance: { label: "Performance", icon: "target" },
  helpdesk: { label: "Helpdesk", icon: "ring_buoy" },
  assets: { label: "Assets", icon: "laptop" },
  exits: { label: "Exits", icon: "door" },
  general: { label: "Other updates", icon: "bell" },
};
