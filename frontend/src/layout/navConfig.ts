import type { NavEntry } from "../api/client";

// Part 15 app shell: the menu comes from GET /api/me/bootstrap (module registry x enablement x
// permissions, each entry carrying its sidebar group and emoji name). This static list is
// only what shows until bootstrap loads (or if it fails), so the app is never menu-less.

export type NavGroup = NonNullable<NavEntry["group"]>;

export const NAV_GROUP_ORDER: NavGroup[] = ["today", "hiring", "people", "insights", "admin"];

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
  { label_key: "nav.people", path: "/people", group: "people", icon: "people" },
  { label_key: "nav.helpdesk", path: "/helpdesk", group: "people", icon: "ring_buoy" },
  { label_key: "nav.reports", path: "/reports", group: "insights", icon: "bar_chart" },
  { label_key: "nav.settings", path: "/settings", group: "admin", icon: "gear" },
];

// Sub-pages shown under a menu item (keyed by the section's path prefix).
export const NAV_CHILDREN: Record<string, { labelKey: string; path: string; permission?: string }[]> = {
  "/candidates": [
    { labelKey: "nav.sub.dashboard", path: "/candidates/dashboard" },
    { labelKey: "nav.sub.all_candidates", path: "/candidates/list" },
    { labelKey: "nav.sub.import", path: "/candidates/import" },
    { labelKey: "nav.recycle_bin", path: "/candidates/recycle-bin", permission: "recruitment.candidate.delete" },
  ],
  "/screening": [
    { labelKey: "nav.sub.dashboard", path: "/screening/dashboard" },
    { labelKey: "nav.sub.screening_list", path: "/screening/list" },
  ],
  "/shortlisting": [
    { labelKey: "nav.sub.dashboard", path: "/shortlisting/dashboard" },
    { labelKey: "nav.sub.shortlist", path: "/shortlisting/list" },
  ],
  "/interviews": [
    { labelKey: "nav.sub.dashboard", path: "/interviews/dashboard" },
    { labelKey: "nav.sub.all_interviews", path: "/interviews/list" },
    { labelKey: "nav.sub.my_interviews", path: "/interviews/my" },
    { labelKey: "nav.sub.my_availability", path: "/interviews/availability" },
    { labelKey: "nav.sub.interviewers", path: "/interviews/interviewers" },
  ],
  "/performance": [
    { labelKey: "nav.sub.my_performance", path: "/performance" },
    { labelKey: "nav.sub.my_team", path: "/performance/team" },
  ],
  "/helpdesk": [
    { labelKey: "nav.sub.my_tickets", path: "/helpdesk" },
    { labelKey: "nav.sub.ticket_queue", path: "/helpdesk/queue" },
  ],
  "/reports": [
    { labelKey: "nav.sub.all_reports", path: "/reports" },
    { labelKey: "nav.report_builder", path: "/reports/builder" },
  ],
};

export function sectionOf(path: string): string {
  const clean = path.split("#")[0];
  const first = clean.split("/").filter(Boolean)[0];
  return first ? `/${first}` : "/";
}

// Bell groups (L-H5): module -> label key + emoji name.
export const NOTIFICATION_MODULES: Record<string, { labelKey: string; icon: string }> = {
  hiring: { labelKey: "nav.group.hiring", icon: "briefcase" },
  approvals: { labelKey: "nav.approvals", icon: "check" },
  onboarding: { labelKey: "nav.onboarding", icon: "waving_hand" },
  people: { labelKey: "nav.group.people", icon: "people" },
  performance: { labelKey: "nav.performance", icon: "target" },
  helpdesk: { labelKey: "nav.helpdesk", icon: "ring_buoy" },
  assets: { labelKey: "nav.assets", icon: "laptop" },
  exits: { labelKey: "nav.exits", icon: "door" },
  general: { labelKey: "shell.other_updates", icon: "bell" },
};
