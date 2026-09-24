import type { UserRole } from "../api/types";

// Mirrors the require_roles(...) calls in each backend/app/*/router.py.
export const ROLE_MATRIX = {
  jobsWrite: ["recruiter", "admin"],
  candidatesWrite: ["recruiter", "admin"],
  applicationsCreate: ["recruiter", "admin"],
  screeningDecisions: ["recruiter", "hiring_manager", "admin"],
  interviewsWrite: ["recruiter", "interviewer", "hiring_manager", "admin"],
  salaryWrite: ["hiring_manager", "admin"],
  bgvWrite: ["recruiter", "admin"],
  offersWrite: ["recruiter", "admin"],
  hrIntegrationWrite: ["admin"],
  // Mirrors platform/settings/router.py's require_roles("admin") (Part 2).
  platformSettingsWrite: ["admin"],
  // Same gating as POST /applications/{id}/message -- viewing the HR Inbox list is not
  // admin-only, only configuring the mailbox's SMTP/IMAP settings (hrIntegrationWrite) is.
  hrInboxView: ["recruiter", "hiring_manager", "admin"],
} satisfies Record<string, UserRole[]>;

export function roleAllows(role: UserRole | undefined, allowed: readonly UserRole[]): boolean {
  return role != null && allowed.includes(role);
}
