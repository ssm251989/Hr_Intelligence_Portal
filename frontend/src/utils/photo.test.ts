import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCandidatePhotoUrl } from "./photo";

const fetchPhotoBlobMock = vi.fn();

vi.mock("../api/client", () => ({
  candidatesApi: {
    fetchPhotoBlob: (...args: unknown[]) => fetchPhotoBlobMock(...args),
  },
}));

describe("useCandidatePhotoUrl", () => {
  beforeEach(() => {
    fetchPhotoBlobMock.mockReset();
  });

  it("fetches the photo through the authenticated API and returns a blob URL -- not the raw (unauthenticated) download URL a plain <img src> would need", async () => {
    const blob = new Blob(["fake-image-bytes"], { type: "image/png" });
    fetchPhotoBlobMock.mockResolvedValue(blob);

    const { result } = renderHook(() => useCandidatePhotoUrl("candidate-1", "abc123.png"));

    expect(result.current).toBeNull();

    await waitFor(() => expect(result.current).toMatch(/^blob:/));
    expect(fetchPhotoBlobMock).toHaveBeenCalledWith("candidate-1");
  });

  it("never calls the photo endpoint when there's no photo_path", () => {
    const { result } = renderHook(() => useCandidatePhotoUrl("candidate-1", null));

    expect(result.current).toBeNull();
    expect(fetchPhotoBlobMock).not.toHaveBeenCalled();
  });

  it("falls back to null if the authenticated fetch fails", async () => {
    fetchPhotoBlobMock.mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useCandidatePhotoUrl("candidate-1", "abc123.png"));

    await waitFor(() => expect(fetchPhotoBlobMock).toHaveBeenCalled());
    expect(result.current).toBeNull();
  });
});
