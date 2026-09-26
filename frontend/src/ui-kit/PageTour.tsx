import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { useTheme } from "@mui/material/styles";
import type { EventData, Step } from "react-joyride";

import { useT, type TFunction } from "../i18n";
import { useReducedMotion } from "./motion";

// Part 15 B / L-V4: a react-joyride spotlight tour the FIRST time someone opens a page
// (skippable; "Don't show again" is remembered). Pages mark the parts to point at with
// data-tour="..." attributes; PageHeader already marks its title and primary button.
//   <PageTour tourKey="jobs" steps={[{ target: '[data-tour="jobs-table"]', title: "...", content: "..." }]} />
// "Show me how" -> "Take the tour" replays it via startPageTour(key).

const Joyride = lazy(() => import("react-joyride").then((m) => ({ default: m.Joyride })));
const SEEN_KEY = "hrms.pagetours.seen";
const START_EVENT = "hrms:start-tour";

function seen(): string[] {
  try {
    return JSON.parse(localStorage.getItem(SEEN_KEY) || "[]");
  } catch {
    return [];
  }
}
function markSeen(key: string) {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify([...new Set([...seen(), key])]));
  } catch {
    /* storage blocked: the tour may show again next visit */
  }
}

export function startPageTour(key: string) {
  window.dispatchEvent(new CustomEvent(START_EVENT, { detail: key }));
}

export interface TourStep {
  target: string;
  title: ReactNode;
  content: ReactNode;
}

const defaultSteps = (t: TFunction): TourStep[] => [
  { target: '[data-tour="page-title"]', title: t("tour.what_title"), content: t("tour.what_body") },
  { target: '[data-tour="page-primary"]', title: t("tour.start_title"), content: t("tour.start_body") },
  { target: '[data-tour="global-search"]', title: t("tour.search_title"), content: t("tour.search_body") },
  { target: 'nav[aria-label="Main"]', title: t("tour.menu_title"), content: t("tour.menu_body") },
];

export default function PageTour({ tourKey, steps, autoStart = true }: { tourKey: string; steps?: TourStep[]; autoStart?: boolean }) {
  const theme = useTheme();
  const t = theme.palette.fresh;
  const reduced = useReducedMotion();
  const tt = useT();
  const [run, setRun] = useState(false);

  useEffect(() => {
    // Wait a beat so the page's data (and the targets) have rendered.
    const timer = autoStart && !seen().includes(tourKey) ? window.setTimeout(() => setRun(true), 900) : undefined;
    const onStart = (e: Event) => {
      if ((e as CustomEvent<string>).detail === tourKey) setRun(true);
    };
    window.addEventListener(START_EVENT, onStart);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener(START_EVENT, onStart);
    };
  }, [tourKey, autoStart]);

  if (!run) return null;
  const available = (steps ?? defaultSteps(tt)).filter((s) => document.querySelector(s.target));
  if (!available.length) return null;

  const joySteps: Step[] = available.map((s) => ({ target: s.target, title: s.title, content: s.content, skipBeacon: true }));
  const onEvent = (data: EventData) => {
    const status = (data as unknown as { status?: string }).status;
    if (status === "finished" || status === "skipped") {
      markSeen(tourKey);
      setRun(false);
    }
  };

  return (
    <Suspense fallback={null}>
      <Joyride
        steps={joySteps}
        run
        continuous
        onEvent={onEvent}
        locale={{ back: tt("action.back"), close: tt("action.close"), last: tt("tour.got_it"), next: tt("action.next"), skip: tt("tour.dont_show") }}
        options={{
          primaryColor: t.brand, textColor: t.ink, backgroundColor: t.surface, arrowColor: t.surface, overlayColor: "rgba(14,20,18,0.45)",
          zIndex: theme.zIndex.modal + 10, showProgress: true, spotlightRadius: 14, scrollDuration: reduced ? 0 : 300,
          buttons: ["back", "skip", "primary"],
        }}
        styles={{
          tooltip: { borderRadius: 16, fontFamily: theme.typography.fontFamily, padding: 18 },
          tooltipTitle: { fontWeight: 800, fontSize: 16, textAlign: "left" },
          tooltipContent: { textAlign: "left", padding: "8px 0 0" },
          buttonPrimary: { borderRadius: 11, fontWeight: 700, padding: "8px 14px" },
          buttonBack: { color: t.muted, fontWeight: 600 },
          buttonSkip: { color: t.muted, fontWeight: 600 },
        }}
      />
    </Suspense>
  );
}
