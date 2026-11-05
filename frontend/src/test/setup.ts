import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

import "@testing-library/jest-dom/vitest";

// Without globals: true in the vite config, React Testing Library's own auto-cleanup
// detection doesn't register -- without this, each test's rendered DOM (including MUI's
// portaled/leftover nodes) leaks into the next test in the same file, silently corrupting
// broad queries like document.querySelector.
afterEach(() => {
  cleanup();
});

// jsdom doesn't implement the Blob URL APIs at all -- anything using useCandidatePhotoUrl
// (candidate photo avatars) would throw "not implemented" without these.
if (!URL.createObjectURL) {
  URL.createObjectURL = () => "blob:mock-url";
}
if (!URL.revokeObjectURL) {
  URL.revokeObjectURL = () => {};
}
