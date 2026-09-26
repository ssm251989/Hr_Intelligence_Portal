import { http } from "./client";
import type { UUID } from "./types";

// Part 15.4 Candidates restyle: small wrappers for the profile screen's extra read-only data
// (backend app/experience/ui_candidates_router.py). Every call degrades to `null` when the
// endpoint is not available, so the screen simply hides that part instead of showing an error.

export interface EvidenceLine {
  skill: string;
  quote: string;
}

export interface ApplicationEvidence {
  application_id: UUID;
  resume_readable: boolean;
  evidence: EvidenceLine[];
  missing_skills: string[];
  job_skills: string[];
}

export const candidatesExtraApi = {
  evidence: async (applicationId: UUID): Promise<ApplicationEvidence | null> => {
    try {
      return await http.get<ApplicationEvidence>(`/api/v1/ui/candidates/applications/${applicationId}/evidence`);
    } catch {
      return null;
    }
  },
  resumeBlob: (candidateId: UUID): Promise<Blob | null> => http.fetchBlob(`/candidates/${candidateId}/resume`),
};
