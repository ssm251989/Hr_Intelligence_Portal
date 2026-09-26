// Part 17.9: ONE "People" section with two views -- Directory (cards everyone can see) and
// HR view (the table with HR-only columns, filters and export). ?view=hr picks the HR view;
// the old /employees and /directory URLs redirect here. Employee profiles open from both.
import { lazy, Suspense } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import { Link as RouterLink, useSearchParams } from "react-router-dom";

import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { useT } from "../../i18n";
import { Emoji, PageHeader } from "../../ui-kit";

const DirectoryPage = lazy(() => import("./DirectoryPage"));
const EmployeesPage = lazy(() => import("./EmployeesPage"));

export default function PeoplePage() {
  const t = useT();
  const { can } = useMeBootstrap();
  const hr = can("core_hr.employee.view");
  const [params, setParams] = useSearchParams();
  const view = hr && params.get("view") === "hr" ? "hr" : "directory";
  const pick = (next: string) => {
    const p = new URLSearchParams(params);
    if (next === "hr") p.set("view", "hr");
    else p.delete("view");
    setParams(p, { replace: true });
  };

  return (
    <Box>
      <PageHeader
        emoji="people"
        title={t("people.section.title")}
        purpose={t(view === "hr" ? "people.section.purpose_hr" : "people.section.purpose")}
        tourKey="people"
        extra={<Button variant="outlined" component={RouterLink} to="/org-chart" startIcon={<Emoji name="building" size={18} />}>{t("people.directory.org_chart")}</Button>}
      />
      {hr && (
        <Tabs value={view} onChange={(_e, v) => pick(v)} sx={{ mb: 2 }} aria-label={t("people.section.views")}>
          <Tab value="directory" label={t("people.section.directory")} />
          <Tab value="hr" label={t("people.section.hr_view")} />
        </Tabs>
      )}
      <Suspense fallback={<CircularProgress sx={{ m: 4 }} aria-label={t("people.section.loading")} />}>
        {view === "hr" ? <EmployeesPage embedded /> : <DirectoryPage embedded />}
      </Suspense>
    </Box>
  );
}
