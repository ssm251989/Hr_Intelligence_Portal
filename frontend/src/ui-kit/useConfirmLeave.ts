import { useEffect, useId } from "react";

import { t } from "../i18n";

// Part 17.13: "Leave without saving?" -- while `dirty` is true:
//  (a) closing / reloading the tab shows the browser's own "Leave site?" prompt (beforeunload);
//  (b) clicking an in-app link (sidebar, breadcrumbs, any <a href>) asks first.
//
// Why not react-router's useBlocker: the installed react-router-dom 7 ships it, but it only
// works inside a *data router* (createBrowserRouter + RouterProvider) and throws under the
// <BrowserRouter> this app uses. So in-app navigation is guarded by catching link clicks
// (capture phase, before React Router's own handler). Not covered: programmatic navigate()
// calls and the browser Back button -- those still leave without asking.
//
// Several screens can be dirty at once (e.g. the job wizard and the scoring editor inside
// it): one shared listener asks ONCE, whichever of them are dirty.

const dirtyOwners = new Set<string>();
let installed = false;

function onBeforeUnload(event: BeforeUnloadEvent) {
  if (dirtyOwners.size === 0) return;
  event.preventDefault();
  // Older browsers need a returnValue; the text itself is never shown by modern browsers.
  event.returnValue = "";
}

function onClickCapture(event: MouseEvent) {
  if (dirtyOwners.size === 0 || event.defaultPrevented || event.button !== 0) return;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; // opens a new tab -- nothing is lost
  const anchor = (event.target as Element | null)?.closest?.("a[href]") as HTMLAnchorElement | null;
  if (!anchor || anchor.target === "_blank" || anchor.hasAttribute("download")) return;
  const href = anchor.getAttribute("href") ?? "";
  if (href.startsWith("#") || href.startsWith("mailto:") || href.startsWith("tel:")) return;
  let next: URL;
  try {
    next = new URL(anchor.href, window.location.href);
  } catch {
    return;
  }
  const here = window.location;
  if (next.origin === here.origin && next.pathname === here.pathname && next.search === here.search) return; // same page
  if (!window.confirm(t("autom.leave.confirm"))) {
    event.preventDefault();
    event.stopPropagation();
  }
}

function sync() {
  const want = dirtyOwners.size > 0;
  if (want && !installed) {
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClickCapture, true);
    installed = true;
  } else if (!want && installed) {
    window.removeEventListener("beforeunload", onBeforeUnload);
    document.removeEventListener("click", onClickCapture, true);
    installed = false;
  }
}

/** Ask before leaving while there are unsaved changes. */
export function useConfirmLeave(dirty: boolean): void {
  const owner = useId();
  useEffect(() => {
    if (!dirty) return;
    dirtyOwners.add(owner);
    sync();
    return () => {
      dirtyOwners.delete(owner);
      sync();
    };
  }, [dirty, owner]);
}

/** For a "Close" / "Cancel" button: true when it is fine to throw the changes away. */
export function confirmDiscard(dirty: boolean): boolean {
  return !dirty || window.confirm(t("autom.leave.confirm"));
}

export default useConfirmLeave;
