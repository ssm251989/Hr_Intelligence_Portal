import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Snackbar from "@mui/material/Snackbar";
import Stack from "@mui/material/Stack";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";
import ReactGridLayout, { useContainerWidth, type Layout } from "react-grid-layout";
import { Link as RouterLink } from "react-router-dom";

import { homeApi, type HomeKind, type LayoutItem, type MyHome } from "../api/homeApi";
import AdminHomeChecklist from "../components/AdminHomeChecklist";
import {
  AlertsWidget, AssetsWidget, FeedbackWidget, GoalsWidget, HiringFlowWidget, LettersWidget, OfficesWidget, StatsWidget, TeamWidget,
  TicketsWidget, TodoWidget,
} from "../components/home/HomeWidgets";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";
import { useT } from "../i18n";
import { Emoji, HomeGreeting, PageTour } from "../ui-kit";

// Part 15.5 / L-N2, O1-O4: one home per role. HR: greeting, 4 number tiles, hiring Sankey,
// to-do by urgency, people by office, heads-up alerts. Manager: approvals, my team,
// interviews needing feedback, team goals. Employee: my tasks, goals, tickets, assets,
// letters. People drag/resize the boxes (saved per person); an admin can save a layout as
// the company default for each home.

type WidgetKey =
  | "stats" | "flow" | "todo" | "offices" | "alerts" | "team" | "feedback" | "team_goals" | "my_goals" | "tickets" | "assets" | "letters";

const DEFAULTS: Record<HomeKind, LayoutItem[]> = {
  hr: [
    { i: "stats", x: 0, y: 0, w: 12, h: 5 },
    { i: "flow", x: 0, y: 5, w: 7, h: 8 },
    { i: "todo", x: 7, y: 5, w: 5, h: 8 },
    { i: "offices", x: 0, y: 13, w: 7, h: 7 },
    { i: "alerts", x: 7, y: 13, w: 5, h: 7 },
  ],
  manager: [
    { i: "todo", x: 0, y: 0, w: 6, h: 8 },
    { i: "feedback", x: 6, y: 0, w: 6, h: 8 },
    { i: "team", x: 0, y: 8, w: 6, h: 8 },
    { i: "team_goals", x: 6, y: 8, w: 6, h: 8 },
    { i: "alerts", x: 0, y: 16, w: 12, h: 5 },
  ],
  employee: [
    { i: "todo", x: 0, y: 0, w: 6, h: 7 },
    { i: "my_goals", x: 6, y: 0, w: 6, h: 7 },
    { i: "tickets", x: 0, y: 7, w: 6, h: 7 },
    { i: "assets", x: 6, y: 7, w: 6, h: 6 },
    { i: "letters", x: 0, y: 14, w: 12, h: 6 },
  ],
};

function widget(key: string, editing: boolean): ReactNode {
  switch (key as WidgetKey) {
    case "stats": return <StatsWidget />;
    case "flow": return <HiringFlowWidget editing={editing} />;
    case "todo": return <TodoWidget editing={editing} />;
    case "offices": return <OfficesWidget editing={editing} />;
    case "alerts": return <AlertsWidget editing={editing} />;
    case "team": return <TeamWidget editing={editing} />;
    case "feedback": return <FeedbackWidget editing={editing} />;
    case "team_goals": return <GoalsWidget team editing={editing} />;
    case "my_goals": return <GoalsWidget editing={editing} />;
    case "tickets": return <TicketsWidget editing={editing} />;
    case "assets": return <AssetsWidget editing={editing} />;
    case "letters": return <LettersWidget editing={editing} />;
    default: return null;
  }
}

// Part 18.5: boxes that belong to a module which can be switched off
const WIDGET_MODULE: Partial<Record<string, string>> = { team_goals: "performance", my_goals: "performance", tickets: "helpdesk", assets: "assets" };

/** A saved layout only ever REARRANGES this home's boxes: unknown keys drop, new boxes join. */
function reconcile(kind: HomeKind, saved: LayoutItem[] | null, modules?: string[]): LayoutItem[] {
  const on = (key: string) => !WIDGET_MODULE[key] || !modules || modules.includes(WIDGET_MODULE[key]!);
  const base = DEFAULTS[kind].filter((b) => on(b.i));
  if (!saved?.length) return base;
  const known = new Set(base.map((b) => b.i));
  const kept = saved.filter((s) => known.has(s.i));
  const missing = base.filter((b) => !kept.some((k) => k.i === b.i)).map((b) => ({ ...b, y: 999 }));
  return [...kept, ...missing];
}

export default function HomePage() {
  const t = useT();
  const theme = useTheme();
  const f = theme.palette.fresh;
  const wide = useMediaQuery(theme.breakpoints.up("md"));
  const { can, data: me } = useMeBootstrap();
  const modules = me?.modules;
  const [home, setHome] = useState<MyHome | null>(null);
  const [preview, setPreview] = useState<HomeKind | null>(null);
  const [layout, setLayout] = useState<LayoutItem[]>([]);
  const [editing, setEditing] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const { width, containerRef, mounted } = useContainerWidth();
  const saveTimer = useRef<number | undefined>(undefined);

  const load = useCallback((kind?: HomeKind) => {
    homeApi.mine(kind).then((h) => {
      setHome(h);
      setLayout(reconcile(h.kind, h.layout, modules));
    }).catch(() => {
      const fallback: MyHome = { kind: "employee", own_kind: "employee", layout: null, layout_source: "built_in", can_set_defaults: false };
      setHome(fallback);
      setLayout(reconcile("employee", null, modules));
    });
  }, [modules]);

  useEffect(() => load(preview ?? undefined), [load, preview]);

  const kind = home?.kind ?? "employee";
  const ownHome = home ? home.kind === home.own_kind : true;

  const onLayoutChange = (next: Layout) => {
    const clean = next.map(({ i, x, y, w, h }) => ({ i, x, y, w, h }));
    setLayout(clean);
    if (!editing || !ownHome) return;
    window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      homeApi.saveLayout(kind, clean).then(() => setToast(t("home.saved"))).catch(() => undefined);
    }, 700);
  };

  const reset = () => {
    homeApi.resetLayout(kind).then(() => load(preview ?? undefined)).catch(() => undefined);
    setEditing(false);
  };

  const saveAsDefault = () => {
    homeApi.setCompanyDefault(kind, layout).then(() => setToast(t("home.company_default_saved"))).catch(() => undefined);
  };

  const items = useMemo(() => layout.map((l) => ({ ...l, minW: 3, minH: 4 })), [layout]);
  const ordered = useMemo(() => [...layout].sort((a, b) => a.y - b.y || a.x - b.x), [layout]);

  const controls = (
    <>
      {kind === "hr" && can("recruitment.job.edit") && (
        <Button variant="outlined" component={RouterLink} to="/jobs" startIcon={<Emoji name="briefcase" size={16} />}>{t("home.new_job")}</Button>
      )}
      {wide && (
        <Button variant={editing ? "contained" : "outlined"} color={editing ? "secondary" : "primary"} onClick={() => setEditing((e) => !e)}
          startIcon={<Emoji name={editing ? "check" : "tools"} size={16} />}>
          {editing ? t("home.arrange_done") : t("home.arrange")}
        </Button>
      )}
    </>
  );

  return (
    <Box>
      {ownHome ? <HomeGreeting extra={controls} /> : null}
      <AdminHomeChecklist />

      {home?.can_set_defaults && wide && (
        <Stack direction="row" spacing={1.5} alignItems="center" flexWrap="wrap" sx={{ mb: 2, rowGap: 1 }}>
          <Typography sx={{ fontWeight: 700, fontSize: 13, color: f.muted }}>{t("home.preview_as")}</Typography>
          <ToggleButtonGroup exclusive size="small" value={kind} onChange={(_e, v: HomeKind | null) => v && setPreview(v === home.own_kind ? null : v)}>
            {(["hr", "manager", "employee"] as HomeKind[]).map((k) => <ToggleButton key={k} value={k}>{t(`home.kind.${k}`)}</ToggleButton>)}
          </ToggleButtonGroup>
          {!ownHome && controls}
          {editing && <Button onClick={saveAsDefault} startIcon={<Emoji name="building" size={16} />}>{t("home.company_default")}</Button>}
        </Stack>
      )}

      {editing && (
        <Alert severity="info" icon={<Emoji name="light_bulb" size={18} />} sx={{ mb: 2 }}
          action={ownHome && home?.layout_source === "mine" ? <Button color="inherit" size="small" onClick={reset}>{t("home.reset")}</Button> : undefined}>
          {t("home.arrange_hint")}
        </Alert>
      )}

      {wide ? (
        <Box ref={containerRef} sx={{ mx: "-9px", "& .react-grid-item.react-grid-placeholder": { bgcolor: f.brandSoft, opacity: 1, borderRadius: "18px" } }}>
          {mounted && home && (
            <ReactGridLayout
              layout={items}
              width={width}
              gridConfig={{ cols: 12, rowHeight: 40, margin: [18, 18] }}
              dragConfig={{ enabled: editing, handle: ".widget-drag" }}
              resizeConfig={{ enabled: editing }}
              onLayoutChange={onLayoutChange}
            >
              {items.map((l) => (
                <Box key={l.i} sx={{ height: "100%" }}>
                  {l.i === "stats" && editing && (
                    <Box className="widget-drag" sx={{ cursor: "grab", textAlign: "center", color: f.muted, fontSize: 12, fontWeight: 700, mb: 0.5 }}>
                      ⠿ {t("home.w.stats")}
                    </Box>
                  )}
                  {widget(l.i, editing)}
                </Box>
              ))}
            </ReactGridLayout>
          )}
        </Box>
      ) : (
        <Stack spacing={2}>
          {ordered.map((l) => <Box key={l.i} sx={{ minHeight: l.i === "stats" ? undefined : 260 }}>{widget(l.i, false)}</Box>)}
        </Stack>
      )}

      <PageTour tourKey={`home-${kind}`} />
      <Snackbar open={Boolean(toast)} autoHideDuration={2500} onClose={() => setToast(null)} message={toast} anchorOrigin={{ vertical: "bottom", horizontal: "center" }} />
    </Box>
  );
}
