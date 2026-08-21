import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import RefreshButton from "./RefreshButton";

describe("RefreshButton", () => {
  it("calls onRefresh when clicked", () => {
    const onRefresh = vi.fn();
    render(<RefreshButton loading={false} onRefresh={onRefresh} />);

    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("disables itself and shows a spinner while loading", () => {
    const onRefresh = vi.fn();
    render(<RefreshButton loading onRefresh={onRefresh} />);

    const button = screen.getByRole("button", { name: "Refresh" });
    expect(button).toBeDisabled();

    fireEvent.click(button);
    expect(onRefresh).not.toHaveBeenCalled();
  });

  it("supports a custom label", () => {
    render(<RefreshButton loading={false} onRefresh={vi.fn()} label="Reload jobs" />);
    expect(screen.getByRole("button", { name: "Reload jobs" })).toBeInTheDocument();
  });
});
