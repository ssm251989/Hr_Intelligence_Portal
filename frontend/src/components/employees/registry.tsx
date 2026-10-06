import type { ReactNode } from "react";

import type { EmployeeRow } from "../../api/employeesApi";

// Part 20: actions that later steps add to the Employees "..." menu and the profile (Make
// interviewer -- 20.4, Start exit -- 20.3). Each renders its own dialog.

export interface EmployeeAction {
  key: string;
  labelKey: string;
  visible: (row: EmployeeRow) => boolean;
  render: (row: EmployeeRow, close: () => void, toast: (msg: string) => void) => ReactNode;
}

export const employeeActionsRegistry: { items: EmployeeAction[] } = { items: [] };
