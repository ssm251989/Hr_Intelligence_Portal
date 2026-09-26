import { Suspense, lazy, useCallback, useRef } from "react";
import { Link as RouterLink } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { ApiError } from "../../api/client";
import { peopleApi, type OrgNode } from "../../api/peopleApi";
import { useMeBootstrap } from "../../bootstrap/MeBootstrapContext";
import { NoAccess } from "../../components/people/shared";
import { useT } from "../../i18n";
import { Emoji, InfoTip, PageHeader } from "../../ui-kit";

// d3 (hierarchy + zoom + selection) only downloads when this page opens.
const OrgChartCanvas = lazy(() => import("../../components/people/OrgChartCanvas"));

export default function OrgChartPage() {
  const t = useT();
  const f = useTheme().palette.fresh;
  const { can, loading: bootLoading } = useMeBootstrap();
  const canView = can("core_hr.org.view");
  // If the page helper isn't available, fall back to the plain org chart (no names/photos).
  const basicOnly = useRef(false);

  const loadLevel = useCallback(async (rootPositionId?: string): Promise<OrgNode[]> => {
    if (!basicOnly.current) {
      try {
        return (await peopleApi.orgChart(rootPositionId)).nodes;
      } catch (err) {
        if (!(err instanceof ApiError && err.status === 404)) throw err;
        basicOnly.current = true;
      }
    }
    return peopleApi.orgChartBasic(rootPositionId);
  }, []);

  if (!bootLoading && !canView) {
    return (
      <Box>
        <PageHeader emoji="building" title={t("people.org.title")} purpose={t("people.org.purpose")} />
        <NoAccess emoji="building" />
      </Box>
    );
  }

  return (
    <Box>
      <PageHeader
        emoji="building"
        title={t("people.org.title")}
        purpose={t("people.org.purpose")}
        tourKey="org_chart"
        primary={<Button variant="contained" component={RouterLink} to="/directory" startIcon={<Emoji name="people" size={18} />}>{t("people.org.find_person")}</Button>}
      />
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1.5, flexWrap: "wrap", rowGap: 1 }}>
        <Typography sx={{ color: f.muted, fontSize: 14, display: "flex", alignItems: "center" }}>
          {t("people.org.how")}
          <InfoTip text={t("people.org.how_tip")} />
        </Typography>
      </Stack>
      <Suspense fallback={<Card sx={{ height: 480, display: "grid", placeItems: "center" }}><CircularProgress aria-label={t("people.org.loading")} /></Card>}>
        <OrgChartCanvas loadLevel={loadLevel} />
      </Suspense>
    </Box>
  );
}
