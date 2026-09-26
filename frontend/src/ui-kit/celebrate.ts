import { celebrationsApi } from "../api/client";
import { prefersReducedMotion } from "./motion";

// L-V3: confetti when an offer is signed or a joiner is marked joined -- ONCE per user per
// event. The server remembers who already celebrated (works across devices); if it can't be
// reached, a per-browser marker stops repeats on this device.
//   celebrate(`offer.signed:${offerId}`)

const LOCAL_KEY = "hrms.celebrated";

function seenLocally(key: string): boolean {
  try {
    return (JSON.parse(localStorage.getItem(LOCAL_KEY) || "[]") as string[]).includes(key);
  } catch {
    return false;
  }
}
function rememberLocally(key: string) {
  try {
    const list = JSON.parse(localStorage.getItem(LOCAL_KEY) || "[]") as string[];
    localStorage.setItem(LOCAL_KEY, JSON.stringify([...list.slice(-200), key]));
  } catch {
    /* storage blocked -- the server marker still applies */
  }
}

export async function celebrate(eventKey: string, colours?: string[]): Promise<boolean> {
  const key = eventKey.toLowerCase().replace(/[^a-z0-9_.:-]/g, "-");
  if (seenLocally(key)) return false;
  let first = true;
  try {
    first = (await celebrationsApi.once(key)).first;
  } catch {
    first = true;
  }
  rememberLocally(key);
  if (!first || prefersReducedMotion()) return first;
  const { default: confetti } = await import("canvas-confetti");
  const css = getComputedStyle(document.documentElement);
  const theme = ["--brand", "--sun", "--coral", "--sky"].map((v) => css.getPropertyValue(v).trim()).filter(Boolean);
  confetti({ particleCount: 120, spread: 75, origin: { y: 0.7 }, colors: colours ?? (theme.length ? theme : undefined), disableForReducedMotion: true });
  return true;
}
