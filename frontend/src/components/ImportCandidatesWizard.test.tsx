import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ApplicationRead, CandidateRead, JobRoleRead } from "../api/types";
import ImportCandidatesWizard from "./ImportCandidatesWizard";

const uploadMock = vi.fn();
const parseResumeMock = vi.fn();
const listApplicationsMock = vi.fn();
const jobsListMock = vi.fn();
const applicationsCreateMock = vi.fn();

vi.mock("../api/client", () => ({
  candidatesApi: {
    upload: (...args: unknown[]) => uploadMock(...args),
    parseResume: (...args: unknown[]) => parseResumeMock(...args),
    listApplications: (...args: unknown[]) => listApplicationsMock(...args),
  },
  jobsApi: {
    list: (...args: unknown[]) => jobsListMock(...args),
  },
  applicationsApi: {
    create: (...args: unknown[]) => applicationsCreateMock(...args),
  },
  extractErrorMessage: (err: unknown, fallback: string) => (err instanceof Error ? err.message : fallback),
}));

const JOB: JobRoleRead = {
  id: "job-1",
  title: "Backend Engineer",
  positions_count: 1,
  job_type: "Full-time",
  status: "published",
  published_platforms: {},
  publish_settings: {},
  created_at: "2026-08-01T00:00:00Z",
  application_count: 0,
};

function makeCandidate(id: string): CandidateRead {
  return {
    id,
    full_name: null,
    email: null,
    phone: null,
    location: null,
    resume_path: `${id}.pdf`,
    photo_path: null,
    parsed_fields: null,
    source: "local_import",
    created_at: "2026-08-11T00:00:00Z",
  };
}

function makeApplication(candidateId: string): ApplicationRead {
  return {
    id: `app-for-${candidateId}`,
    job_role_id: JOB.id,
    candidate_id: candidateId,
    status: "received",
    created_at: "2026-08-11T00:00:00Z",
    updated_at: "2026-08-11T00:00:00Z",
  };
}

async function selectJob() {
  const combobox = screen.getByRole("combobox", { name: "Job" });
  fireEvent.mouseDown(combobox);
  // findBy*, not getBy*: jobsApi.list() resolves asynchronously, so the option for JOB.title
  // may not exist yet at the instant the menu opens -- MUI keeps the already-open menu's
  // items in sync with the `jobs` state as it updates, so waiting here (rather than
  // re-opening) is enough.
  fireEvent.click(await screen.findByRole("option", { name: JOB.title }));
}

async function selectSourceThenConfigure(files: File[]) {
  fireEvent.click(screen.getByText("Local Import"));
  fireEvent.click(screen.getByRole("button", { name: "Next" }));
  await selectJob();
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files } });
}

describe("ImportCandidatesWizard -- Import from Local (multi-file upload/parse)", () => {
  beforeEach(() => {
    uploadMock.mockReset();
    parseResumeMock.mockReset();
    listApplicationsMock.mockReset();
    jobsListMock.mockReset().mockResolvedValue([JOB]);
    applicationsCreateMock.mockReset();
  });

  it("requires a job to be selected before importing -- files alone aren't enough", async () => {
    const fileA = new File(["a"], "alice.pdf", { type: "application/pdf" });

    render(<ImportCandidatesWizard open onClose={vi.fn()} onImported={vi.fn()} initialSource={null} />);

    fireEvent.click(screen.getByText("Local Import"));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    // No job selected -- only choose a file.
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [fileA] } });
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    expect(await screen.findByText("Select a job to link these candidates to")).toBeInTheDocument();
    expect(uploadMock).not.toHaveBeenCalled();
  });

  it("uploads, parses, and links every selected file to the chosen job as a real application", async () => {
    const fileA = new File(["a"], "alice.pdf", { type: "application/pdf" });
    const fileB = new File(["b"], "bob.pdf", { type: "application/pdf" });
    uploadMock.mockResolvedValueOnce(makeCandidate("cand-a")).mockResolvedValueOnce(makeCandidate("cand-b"));
    parseResumeMock.mockResolvedValue(makeCandidate("cand-a"));
    applicationsCreateMock
      .mockResolvedValueOnce(makeApplication("cand-a"))
      .mockResolvedValueOnce(makeApplication("cand-b"));
    const onImported = vi.fn();

    render(<ImportCandidatesWizard open onClose={vi.fn()} onImported={onImported} initialSource={null} />);

    await selectSourceThenConfigure([fileA, fileB]);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(screen.getByText("Imported 2 of 2.")).toBeInTheDocument());

    expect(uploadMock).toHaveBeenCalledTimes(2);
    expect(uploadMock).toHaveBeenNthCalledWith(1, fileA, "local_import");
    expect(uploadMock).toHaveBeenNthCalledWith(2, fileB, "local_import");
    expect(parseResumeMock).toHaveBeenCalledTimes(2);
    expect(applicationsCreateMock).toHaveBeenCalledTimes(2);
    expect(applicationsCreateMock).toHaveBeenNthCalledWith(1, { job_role_id: JOB.id, candidate_id: "cand-a" });
    expect(applicationsCreateMock).toHaveBeenNthCalledWith(2, { job_role_id: JOB.id, candidate_id: "cand-b" });
    expect(onImported).toHaveBeenCalledTimes(1);
    // No failure table when nothing failed.
    expect(screen.queryByText("File")).not.toBeInTheDocument();
  });

  it("reports partial failure: lists the failed file with its reason, still imports and links the rest", async () => {
    const goodFile = new File(["a"], "good-resume.pdf", { type: "application/pdf" });
    const badFile = new File(["b"], "bad-resume.txt", { type: "text/plain" });
    uploadMock
      .mockResolvedValueOnce(makeCandidate("cand-good"))
      .mockRejectedValueOnce(new Error("Only PDF and DOCX resumes are supported"));
    parseResumeMock.mockResolvedValue(makeCandidate("cand-good"));
    applicationsCreateMock.mockResolvedValueOnce(makeApplication("cand-good"));

    render(<ImportCandidatesWizard open onClose={vi.fn()} onImported={vi.fn()} initialSource={null} />);

    await selectSourceThenConfigure([goodFile, badFile]);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(screen.getByText("Imported 1 of 2, 1 failed.")).toBeInTheDocument());

    expect(screen.getByText("bad-resume.txt")).toBeInTheDocument();
    expect(screen.getByText("Only PDF and DOCX resumes are supported")).toBeInTheDocument();
    // The failed file must not have been sent to parse-resume or linked to the job at all.
    expect(parseResumeMock).toHaveBeenCalledTimes(1);
    expect(applicationsCreateMock).toHaveBeenCalledTimes(1);
  });

  it("reports a failure when the candidate uploads fine but linking to the job fails", async () => {
    const file = new File(["a"], "resume.pdf", { type: "application/pdf" });
    uploadMock.mockResolvedValueOnce(makeCandidate("cand-a"));
    parseResumeMock.mockResolvedValue(makeCandidate("cand-a"));
    applicationsCreateMock.mockRejectedValueOnce(new Error("Job role not found"));

    render(<ImportCandidatesWizard open onClose={vi.fn()} onImported={vi.fn()} initialSource={null} />);

    await selectSourceThenConfigure([file]);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(screen.getByText("Imported 0 of 1, 1 failed.")).toBeInTheDocument());
    expect(screen.getByText("Job role not found")).toBeInTheDocument();
  });

  it("shows live progress while files are still being processed", async () => {
    const fileA = new File(["a"], "alice.pdf", { type: "application/pdf" });
    const fileB = new File(["b"], "bob.pdf", { type: "application/pdf" });
    let resolveFirstUpload: (value: CandidateRead) => void = () => {};
    uploadMock
      .mockImplementationOnce(() => new Promise((resolve) => { resolveFirstUpload = resolve; }))
      .mockResolvedValueOnce(makeCandidate("cand-b"));
    parseResumeMock.mockResolvedValue(makeCandidate("cand-a"));
    applicationsCreateMock.mockResolvedValue(makeApplication("cand-a"));

    render(<ImportCandidatesWizard open onClose={vi.fn()} onImported={vi.fn()} initialSource={null} />);

    await selectSourceThenConfigure([fileA, fileB]);
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => expect(screen.getByText("Processing 0 of 2...")).toBeInTheDocument());

    resolveFirstUpload(makeCandidate("cand-a"));

    await waitFor(() => expect(screen.getByText("Imported 2 of 2.")).toBeInTheDocument());
  });
});
