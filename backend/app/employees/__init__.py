"""Part 20: Employees list, automatic employee creation, test email provider, self-service exits,
employees as interviewers (docs/PART20_EMPLOYEES_AND_SELF_SERVICE.txt).

Lives beside the older Core HR module (app/core_hr, the hidden "People" module): it reads and writes
the same `employees` / `employment_records` rows, but its API (/api/v1/ui/employees) is not switched
off with that module -- the Employees tab is always there.
"""
