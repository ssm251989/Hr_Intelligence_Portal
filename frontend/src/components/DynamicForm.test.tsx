import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import DynamicForm from "./DynamicForm";

const effectiveLayoutMock = vi.fn();

vi.mock("../api/client", () => ({
  metadataApi: {
    effectiveLayout: (...args: unknown[]) => effectiveLayoutMock(...args),
  },
}));

const LAYOUT_WITH_FIELDS = {
  entity: "candidate",
  context: "create",
  sections: [],
  custom_fields: [
    { code: "favorite_color", label_i18n: { en: "Favorite Color" }, type: "text", validation: null, default: null, required_condition: null, visible_condition: null, section: "General", order: 1, sensitive: false },
    { code: "shirt_size", label_i18n: { en: "Shirt Size" }, type: "picklist", validation: { options: ["S", "M", "L"] }, default: null, required_condition: null, visible_condition: null, section: "General", order: 2, sensitive: false },
    {
      code: "visa_number", label_i18n: { en: "Visa Number" }, type: "text", validation: null, default: null,
      required_condition: { "==": [{ var: "needs_visa" }, true] }, visible_condition: { "==": [{ var: "needs_visa" }, true] }, section: "Immigration", order: 1, sensitive: false,
    },
  ],
};

describe("DynamicForm", () => {
  beforeEach(() => {
    effectiveLayoutMock.mockReset();
  });

  it("renders a text input for a text custom field", async () => {
    effectiveLayoutMock.mockResolvedValue(LAYOUT_WITH_FIELDS);
    render(<DynamicForm entity="candidate" context="create" values={{}} onChange={() => {}} />);

    expect(await screen.findByLabelText("Favorite Color")).toBeInTheDocument();
  });

  it("calls onChange with the updated value when a text field changes", async () => {
    effectiveLayoutMock.mockResolvedValue(LAYOUT_WITH_FIELDS);
    const onChange = vi.fn();
    render(<DynamicForm entity="candidate" context="create" values={{}} onChange={onChange} />);

    const input = await screen.findByLabelText("Favorite Color");
    fireEvent.change(input, { target: { value: "blue" } });

    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ favorite_color: "blue" }));
  });

  it("renders a labeled select for a picklist field", async () => {
    effectiveLayoutMock.mockResolvedValue(LAYOUT_WITH_FIELDS);
    render(<DynamicForm entity="candidate" context="create" values={{}} onChange={() => {}} />);

    expect(await screen.findByLabelText("Shirt Size")).toBeInTheDocument();
  });

  it("hides a field whose visible_condition does not hold", async () => {
    effectiveLayoutMock.mockResolvedValue(LAYOUT_WITH_FIELDS);
    render(<DynamicForm entity="candidate" context="create" values={{ needs_visa: false }} onChange={() => {}} />);

    await screen.findByLabelText("Favorite Color"); // wait for load
    expect(screen.queryByLabelText("Visa Number")).not.toBeInTheDocument();
  });

  it("shows a field once its visible_condition holds", async () => {
    effectiveLayoutMock.mockResolvedValue(LAYOUT_WITH_FIELDS);
    render(<DynamicForm entity="candidate" context="create" values={{ needs_visa: true }} onChange={() => {}} />);

    expect(await screen.findByLabelText("Visa Number")).toBeInTheDocument();
  });

  it("shows a Required hint when required_condition holds", async () => {
    effectiveLayoutMock.mockResolvedValue(LAYOUT_WITH_FIELDS);
    render(<DynamicForm entity="candidate" context="create" values={{ needs_visa: true }} onChange={() => {}} />);

    await screen.findByLabelText("Visa Number");
    expect(screen.getByText("Required")).toBeInTheDocument();
  });

  it("shows a field-level validation error passed via errors prop", async () => {
    effectiveLayoutMock.mockResolvedValue(LAYOUT_WITH_FIELDS);
    render(<DynamicForm entity="candidate" context="create" values={{}} onChange={() => {}} errors={{ favorite_color: "is not a defined custom field for this entity" }} />);

    await screen.findByLabelText("Favorite Color");
    expect(screen.getByText("is not a defined custom field for this entity")).toBeInTheDocument();
  });

  it("renders a message when there are no custom fields for this entity/context", async () => {
    effectiveLayoutMock.mockResolvedValue({ entity: "candidate", context: "portal", sections: [], custom_fields: [] });
    render(<DynamicForm entity="candidate" context="portal" values={{}} onChange={() => {}} />);

    expect(await screen.findByText(/No custom fields defined/)).toBeInTheDocument();
  });

  it("fetches the layout for the given entity/context", async () => {
    effectiveLayoutMock.mockResolvedValue(LAYOUT_WITH_FIELDS);
    render(<DynamicForm entity="candidate" context="create" values={{}} onChange={() => {}} />);

    await waitFor(() => expect(effectiveLayoutMock).toHaveBeenCalledWith("candidate", "create"));
  });
});
