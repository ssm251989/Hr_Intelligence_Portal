export interface JobSkillFields {
  technical_skills_must_have?: string[] | null;
  technical_skills_good_to_have?: string[] | null;
  soft_skills_must_have?: string[] | null;
  soft_skills_good_to_have?: string[] | null;
}

// Shared by every place a job's 4 categorized skill lists are displayed (Job Details
// dialog, Careers list/detail pages) -- combines technical + soft within each of the 2
// severity tiers so "Must Have" can be shown more prominently than "Good to Have"
// without the display needing to also distinguish technical from soft.
export function categorizeSkills(job: JobSkillFields): { mustHave: string[]; goodToHave: string[] } {
  return {
    mustHave: [...(job.technical_skills_must_have || []), ...(job.soft_skills_must_have || [])],
    goodToHave: [...(job.technical_skills_good_to_have || []), ...(job.soft_skills_good_to_have || [])],
  };
}
