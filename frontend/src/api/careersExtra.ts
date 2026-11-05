import { http } from "./client";

// Part 15.4 careers portal: public extras (backend app/experience/ui_careers_router.py).
// Both calls degrade to "nothing to show" if the endpoint isn't deployed yet, so the
// career site never breaks because of them.

export interface CareersBenefit {
  title: string;
  body: string;
  emoji: string | null;
}

export interface CareersFaq {
  question: string;
  answer: string;
}

export interface CareersSite {
  intro: string | null;
  benefits: CareersBenefit[];
  faq: CareersFaq[];
}

export interface CareersJobExtras {
  job_type: string | null;
  benefits: string | null;
  application_deadline: string | null;
}

const EMPTY_SITE: CareersSite = { intro: null, benefits: [], faq: [] };

export const careersExtraApi = {
  site: () => http.get<CareersSite>("/api/v1/public/careers/site").catch(() => EMPTY_SITE),
  jobExtras: (jobId: string) =>
    http.get<CareersJobExtras>(`/api/v1/public/careers/jobs/${jobId}/extras`).catch((): CareersJobExtras | null => null),
};
