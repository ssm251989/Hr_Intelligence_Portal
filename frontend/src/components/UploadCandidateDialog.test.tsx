import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CandidateRead } from "../api/types";
import UploadCandidateDialog from "./UploadCandidateDialog";

const uploadMock = vi.fn();
const parseResumeMock = vi.fn();

vi.mock("../api/client", () => ({
  candidatesApi: {
    upload: (...args: unknown[]) => uploadMock(...args),
    parseResume: (...args: unknown[]) => parseResumeMock(...args),
    // Both fixtures below have photo_path: null, so CandidateAvatar's photo hook never
    // actually calls this -- stubbed anyway so the mock module shape stays complete.
    fetchPhotoBlob: vi.fn().mockResolvedValue(null),
  },
  applicationsApi: {
    create: vi.fn(),
  },
  jobsApi: {
    list: vi.fn().mockResolvedValue([]),
  },
  extractErrorMessage: (_err: unknown, fallback: string) => fallback,
}));

const UNPARSED_CANDIDATE: CandidateRead = {
  id: "candidate-1",
  full_name: null,
  email: null,
  phone: null,
  location: null,
  resume_path: "resume.docx",
  photo_path: null,
  parsed_fields: null,
  source: "manual",
  created_at: "2026-08-11T00:00:00Z",
};

const PARSED_CANDIDATE: CandidateRead = {
  ...UNPARSED_CANDIDATE,
  full_name: "Jane Doe",
  email: "jane@example.com",
  parsed_fields: {
    full_name: "Jane Doe",
    email: "jane@example.com",
    skills: [],
    education: [],
    work_history: [],
  },
};

function selectFile() {
  const file = new File(["resume contents"], "resume.docx", {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
  const input = document.querySelector('input[type="file"]') as HTMLInputElement;
  fireEvent.change(input, { target: { files: [file] } });
}

describe("UploadCandidateDialog", () => {
  beforeEach(() => {
    uploadMock.mockReset();
    parseResumeMock.mockReset();
  });

  it("calls parse-resume automatically right after a successful upload", async () => {
    uploadMock.mockResolvedValue(UNPARSED_CANDIDATE);
    parseResumeMock.mockResolvedValue(PARSED_CANDIDATE);

    render(<UploadCandidateDialog open onClose={vi.fn()} />);

    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(uploadMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(parseResumeMock).toHaveBeenCalledTimes(1));
    expect(parseResumeMock).toHaveBeenCalledWith(UNPARSED_CANDIDATE.id);

    // The parsed name/photo confirmation renders once parsing resolves, proving the
    // dialog actually surfaces the parse-resume result rather than just calling it.
    await waitFor(() => expect(screen.getByText("Jane Doe")).toBeInTheDocument());
  });

  it("still lets the recruiter link the candidate to a job when parsing fails", async () => {
    uploadMock.mockResolvedValue(UNPARSED_CANDIDATE);
    parseResumeMock.mockRejectedValue(new Error("AI service unavailable"));

    render(<UploadCandidateDialog open onClose={vi.fn()} />);

    selectFile();
    fireEvent.click(screen.getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(parseResumeMock).toHaveBeenCalledTimes(1));

    // Parse failure is surfaced, not swallowed silently -- but doesn't block linking.
    await waitFor(() => expect(screen.getByText(/couldn't automatically parse/i)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Link to Job" })).not.toBeDisabled();
  });
});
