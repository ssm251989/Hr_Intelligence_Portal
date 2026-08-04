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
} satisfies Record<string, UserRole[]>;

export function roleAllows(role: UserRole | undefined, allowed: readonly UserRole[]): boolean {
  return role != null && allowed.includes(role);
}
