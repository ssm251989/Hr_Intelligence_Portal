import type { ReactNode } from "react";

import type { EmployeeRow } from "../../api/employeesApi";
import MakeInterviewerDialog from "./MakeInterviewerDialog";
import StartExitDialog from "./StartExitDialog";

// Part 20: actions that later steps add to the Employees "..." menu and the profile (Make
// interviewer -- 20.4, Start exit -- 20.3). Each renders its own dialog.

export interface EmployeeAction {
  key: string;
  labelKey: string;
  visible: (row: EmployeeRow) => boolean;
  render: (row: EmployeeRow, close: () => void, toast: (msg: string) => void) => ReactNode;
}

export const employeeActionsRegistry: { items: EmployeeAction[] } = {
  items: [
    // Part 20.3: HR starts an exit (Resigned / Terminated / Absconded / Retirement / Contract end)
    // Part 20.4: employee as interviewer
    { key: "make_interviewer", labelKey: "iv20.menu_make", visible: (r) => r.status === "active" && !r.roles.includes("Interviewer"),
      render: (r, close, toast) => <MakeInterviewerDialog row={r} onClose={close} onToast={toast} /> },
    { key: "edit_interviewer", labelKey: "iv20.menu_edit", visible: (r) => r.status === "active" && r.roles.includes("Interviewer"),
      render: (r, close, toast) => <MakeInterviewerDialog row={r} onClose={close} onToast={toast} /> },
    { key: "remove_interviewer", labelKey: "iv20.menu_remove", visible: (r) => r.roles.includes("Interviewer"),
      render: (r, close, toast) => <MakeInterviewerDialog row={r} remove onClose={close} onToast={toast} /> },
    { key: "start_exit", labelKey: "emp.menu.start_exit", visible: (r) => r.status === "active",
      render: (r, close, toast) => <StartExitDialog row={r} onClose={close} onToast={toast} /> },
  ],
};
