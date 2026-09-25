import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import MobileStepper from "@mui/material/MobileStepper";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import HelpOutlineIcon from "@mui/icons-material/HelpOutline";

// Part 14 section 11 (docs/HRMS_COMPLETE_SPEC.txt): a short tour the first time someone opens
// a module, replayable from the "?" button. Deliberately dependency-free (a dialog stepper,
// not a spotlight library) -- L-V4's react-joyride spotlight tours with clips are a later
// upgrade (see docs/build_log.md Part 14). "Seen" is a per-browser UI preference.

interface TourStep {
  title: string;
  body: string;
}

const TOURS: { prefix: string; id: string; steps: TourStep[] }[] = [
  { prefix: "/setup", id: "setup", steps: [
    { title: "Set up in eight steps", body: "Each step turns green on its own when the thing really exists -- a tested mailbox, imported employees -- so the checklist can't drift from reality." },
    { title: "Skip and come back", body: "Optional steps can be skipped. The checklist stays on your home page until everything is done." },
  ] },
  { prefix: "/approvals", id: "inbox", steps: [
    { title: "Everything waiting on you", body: "Approvals from every module land here, oldest first. You can also approve straight from the email you received." },
    { title: "AI suggestions", body: "Agents only suggest. Nothing they propose happens until you approve or edit it." },
  ] },
  { prefix: "/reports", id: "reports", steps: [
    { title: "Build your own report", body: "Pick a dataset, choose columns or group-by, run it. You only ever see data you're allowed to see." },
    { title: "Save and share", body: "Save a report, share it with a role, or schedule it by email. Shared reports run with each viewer's own access." },
  ] },
  { prefix: "/settings", id: "settings", steps: [
    { title: "Every setting explains itself", body: "Each setting shows what it does and what it affects. Search by name, and use History to see or undo a change." },
  ] },
];

const SEEN_KEY = "hrms.tours.seen";

function seen(): string[] {
  try {
    return JSON.parse(localStorage.getItem(SEEN_KEY) || "[]");
  } catch {
    return [];
  }
}

function markSeen(id: string) {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify([...new Set([...seen(), id])]));
  } catch {
    /* storage unavailable: the tour just shows again next time */
  }
}

export default function ModuleTour() {
  const location = useLocation();
  const tour = TOURS.find((t) => location.pathname.startsWith(t.prefix));
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    setStep(0);
    setOpen(Boolean(tour && !seen().includes(tour.id)));
  }, [tour?.id]);

  if (!tour) return null;
  const close = () => {
    markSeen(tour.id);
    setOpen(false);
  };
  const current = tour.steps[step];

  return (
    <>
      <Tooltip title="Tour of this page">
        <IconButton color="inherit" aria-label="Show a short tour of this page" onClick={() => { setStep(0); setOpen(true); }}>
          <HelpOutlineIcon />
        </IconButton>
      </Tooltip>
      <Dialog open={open} onClose={close} maxWidth="xs" fullWidth aria-labelledby="tour-title">
        <DialogTitle id="tour-title">{current.title}</DialogTitle>
        <DialogContent>
          <Typography>{current.body}</Typography>
        </DialogContent>
        <MobileStepper variant="dots" steps={tour.steps.length} position="static" activeStep={step} backButton={null} nextButton={null} sx={{ justifyContent: "center" }} />
        <DialogActions>
          <Button onClick={close}>{step === tour.steps.length - 1 ? "Done" : "Skip"}</Button>
          {step < tour.steps.length - 1 && <Button variant="contained" onClick={() => setStep(step + 1)}>Next</Button>}
        </DialogActions>
      </Dialog>
    </>
  );
}
