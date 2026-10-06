import type { ReactNode } from "react";

import type { EmployeeRow } from "../../api/employeesApi";
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
    { key: "start_exit", labelKey: "emp.menu.start_exit", visible: (r) => r.status === "active",
      render: (r, close, toast) => <StartExitDialog row={r} onClose={close} onToast={toast} /> },
  ],
};
