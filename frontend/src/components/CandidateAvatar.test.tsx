import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CandidateAvatar from "./CandidateAvatar";

const fetchPhotoBlobMock = vi.fn();

vi.mock("../api/client", () => ({
  candidatesApi: {
    fetchPhotoBlob: (...args: unknown[]) => fetchPhotoBlobMock(...args),
  },
}));

describe("CandidateAvatar", () => {
  it("falls back to initials when there's no photo", () => {
    fetchPhotoBlobMock.mockResolvedValue(null);
    render(<CandidateAvatar candidateId="c1" photoPath={null} name="Alex Nobody" email={null} />);
    expect(document.querySelector("img")).toBeNull();
    expect(screen.getByText("AN")).toBeInTheDocument();
  });

  it("shows the real photo once it loads, instead of initials", async () => {
    const blob = new Blob(["fake image bytes"], { type: "image/jpeg" });
    fetchPhotoBlobMock.mockResolvedValue(blob);
    render(<CandidateAvatar candidateId="c2" photoPath="photo.jpg" name="Jane Doe" email={null} />);
    await waitFor(() => {
      const img = document.querySelector("img");
      expect(img).not.toBeNull();
      expect(img!.getAttribute("src")).toMatch(/^blob:/);
    });
  });
});
