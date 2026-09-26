import { useEffect, useState } from "react";

// Part 15 B / L-V8: all motion off under the OS "reduce motion" setting AND the user's own
// preference (bootstrap ux.reduce_motion puts .reduce-motion on <html>).
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined") return true;
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) || document.documentElement.classList.contains("reduce-motion");
}

export function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(prefersReducedMotion);
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(prefersReducedMotion());
    mq?.addEventListener?.("change", update);
    const obs = new MutationObserver(update);
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => {
      mq?.removeEventListener?.("change", update);
      obs.disconnect();
    };
  }, []);
  return reduced;
}
