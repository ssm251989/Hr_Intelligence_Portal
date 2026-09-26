import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import ButtonGroup from "@mui/material/ButtonGroup";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { hierarchy, tree, type HierarchyPointNode } from "d3-hierarchy";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from "d3-zoom";

import type { OrgNode } from "../../api/peopleApi";
import { useT } from "../../i18n";
import { EmptyState, Emoji, FriendlyError, StatusChip, UserAvatar, useReducedMotion } from "../../ui-kit";

// V6/E2 org chart: zoomable, pannable tree (d3-hierarchy layout + d3-zoom). Branches load one
// level at a time from the org chart API when opened. This module (and d3) is only downloaded
// when the Org chart page is opened (React.lazy in OrgChartPage).
// Keyboard: every card is focusable; Enter/Space opens or closes its team; the chart area takes
// + / - to zoom, 0 to fit, and arrow keys to move around.

const W = 232;
const H = 112;
const GAP_X = 28;
const GAP_Y = 64;
const ROOT = "__root__";

interface Item extends OrgNode {
  parentId: string;
  children?: string[]; // undefined = not loaded yet
  open: boolean;
}

interface Datum {
  id: string;
  kids?: Datum[];
}

export default function OrgChartCanvas({ loadLevel }: { loadLevel: (rootPositionId?: string) => Promise<OrgNode[]> }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const reduced = useReducedMotion();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);
  const [items, setItems] = useState<Record<string, Item>>({});
  const [roots, setRoots] = useState<string[] | null>(null);
  const [loadingIds, setLoadingIds] = useState<Set<string>>(new Set());
  const [error, setError] = useState<unknown>(null);
  const didFit = useRef(false);

  const loadRoots = useCallback(() => {
    setError(null);
    setRoots(null);
    loadLevel()
      .then((nodes) => {
        const next: Record<string, Item> = {};
        nodes.forEach((n) => (next[n.id] = { ...n, parentId: ROOT, open: false }));
        setItems(next);
        setRoots(nodes.map((n) => n.id));
        didFit.current = false;
        // open the top person's team straight away when there is a single top position
        if (nodes.length === 1 && nodes[0].has_children) toggleRef.current?.(nodes[0].id, next);
      })
      .catch(setError);
  }, [loadLevel]);

  const toggle = useCallback((id: string, current?: Record<string, Item>) => {
    const src = current ?? itemsRef.current;
    const it = src[id];
    if (!it) return;
    if (it.children !== undefined || !it.has_children) {
      setItems((prev) => ({ ...prev, [id]: { ...prev[id], open: !prev[id].open } }));
      return;
    }
    setLoadingIds((s) => new Set(s).add(id));
    loadLevel(id)
      .then((kids) => {
        setItems((prev) => {
          const next = { ...prev };
          kids.forEach((k) => (next[k.id] = { ...k, parentId: id, open: false }));
          next[id] = { ...next[id], children: kids.map((k) => k.id), open: true };
          return next;
        });
      })
      .catch(setError)
      .finally(() => setLoadingIds((s) => { const n = new Set(s); n.delete(id); return n; }));
  }, [loadLevel]);

  const itemsRef = useRef(items);
  itemsRef.current = items;
  const toggleRef = useRef(toggle);
  toggleRef.current = toggle;

  useEffect(loadRoots, [loadRoots]);

  // layout
  const layout = useMemo(() => {
    if (!roots) return null;
    const build = (id: string): Datum => {
      const it = items[id];
      return { id, kids: it?.open && it.children ? it.children.map(build) : undefined };
    };
    const rootDatum: Datum = { id: ROOT, kids: roots.map(build) };
    const h = hierarchy<Datum>(rootDatum, (d) => d.kids);
    const laid = tree<Datum>().nodeSize([W + GAP_X, H + GAP_Y])(h);
    const nodes = laid.descendants().filter((n) => n.data.id !== ROOT);
    const links = laid.links().filter((l) => l.source.data.id !== ROOT);
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    nodes.forEach((n) => {
      minX = Math.min(minX, n.x - W / 2); maxX = Math.max(maxX, n.x + W / 2);
      minY = Math.min(minY, n.y); maxY = Math.max(maxY, n.y + H);
    });
    return { nodes, links, bounds: { minX, maxX, minY, maxY } };
  }, [items, roots]);

  // zoom behaviour
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const z = zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 2.5])
      .filter((e: Event & { button?: number; ctrlKey?: boolean; type: string; target: EventTarget | null }) => {
        const target = e.target as Element | null;
        if (target?.closest?.("button,a")) return false;
        return (!e.ctrlKey || e.type === "wheel") && !e.button;
      })
      .on("zoom", (e) => setTransform(e.transform));
    zoomRef.current = z;
    const sel = select(svg);
    sel.call(z).on("dblclick.zoom", null);
    return () => {
      sel.on(".zoom", null);
    };
  }, [roots !== null]); // eslint-disable-line react-hooks/exhaustive-deps

  const fit = useCallback(() => {
    const svg = svgRef.current;
    const z = zoomRef.current;
    if (!svg || !z || !layout || !layout.nodes.length) return;
    const { minX, maxX, minY, maxY } = layout.bounds;
    const cw = svg.clientWidth || 800;
    const ch = svg.clientHeight || 560;
    const pad = 32;
    const k = Math.min(1, (cw - pad * 2) / (maxX - minX || 1), (ch - pad * 2) / (maxY - minY || 1));
    const scale = Math.max(0.2, k);
    const tx = cw / 2 - ((minX + maxX) / 2) * scale;
    const ty = pad - minY * scale;
    select(svg).call(z.transform, zoomIdentity.translate(tx, ty).scale(scale));
  }, [layout]);

  useEffect(() => {
    if (layout && layout.nodes.length && !didFit.current) {
      didFit.current = true;
      fit();
    }
  }, [layout, fit]);

  const zoomBy = (factor: number) => {
    const svg = svgRef.current;
    const z = zoomRef.current;
    if (svg && z) select(svg).call(z.scaleBy, factor);
  };
  const panBy = (dx: number, dy: number) => {
    const svg = svgRef.current;
    const z = zoomRef.current;
    if (svg && z) select(svg).call(z.translateBy, dx / transform.k, dy / transform.k);
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const tag = (e.target as HTMLElement).tagName;
    if (tag === "INPUT" || tag === "TEXTAREA") return;
    const map: Record<string, () => void> = {
      "+": () => zoomBy(1.25), "=": () => zoomBy(1.25), "-": () => zoomBy(0.8), "_": () => zoomBy(0.8), "0": fit,
      ArrowLeft: () => panBy(60, 0), ArrowRight: () => panBy(-60, 0), ArrowUp: () => panBy(0, 60), ArrowDown: () => panBy(0, -60),
    };
    // arrow keys only pan when the chart itself (not a card) has focus
    if (e.key.startsWith("Arrow") && e.target !== wrapRef.current) return;
    const fn = map[e.key];
    if (fn) {
      e.preventDefault();
      fn();
    }
  };

  if (error && !roots) return <FriendlyError error={error} what={t("people.org.load_failed")} onRetry={loadRoots} />;
  if (roots && roots.length === 0) {
    return (
      <Card>
        <EmptyState illustration="team-spirit" title={t("people.org.empty")} hint={t("people.org.empty_hint")}
          action={<Button variant="contained" component={RouterLink} to="/settings">{t("people.org.empty_action")}</Button>} />
      </Card>
    );
  }

  return (
    <Box sx={{ position: "relative" }}>
      <Stack direction="row" spacing={1} alignItems="center" sx={{ position: "absolute", top: 12, right: 12, zIndex: 2 }}>
        <ButtonGroup variant="outlined" size="small" aria-label={t("people.org.zoom_controls")} sx={{ bgcolor: f.surface, borderRadius: "11px" }}>
          <Tooltip title={t("people.org.zoom_in")}><Button onClick={() => zoomBy(1.25)} aria-label={t("people.org.zoom_in")}>＋</Button></Tooltip>
          <Tooltip title={t("people.org.zoom_out")}><Button onClick={() => zoomBy(0.8)} aria-label={t("people.org.zoom_out")}>−</Button></Tooltip>
          <Tooltip title={t("people.org.fit")}><Button onClick={fit}>{t("people.org.fit_short")}</Button></Tooltip>
        </ButtonGroup>
      </Stack>
      {error != null && roots && <Box sx={{ position: "absolute", left: 12, top: 12, right: 200, zIndex: 2 }}><FriendlyError compact error={error} what={t("people.org.branch_failed")} /></Box>}
      <Box
        ref={wrapRef}
        tabIndex={0}
        role="region"
        aria-label={t("people.org.canvas_label")}
        aria-describedby="org-keys"
        onKeyDown={onKeyDown}
        sx={{
          height: { xs: 520, md: "calc(100vh - 290px)" }, minHeight: 480, borderRadius: "18px", border: `1px solid ${f.line}`, bgcolor: f.surface2, overflow: "hidden",
          cursor: "grab", "&:active": { cursor: "grabbing" }, outline: "none", "&:focus-visible": { boxShadow: `0 0 0 3px ${f.brandSoft}`, borderColor: f.brand },
        }}
      >
        {!roots ? (
          <Box sx={{ height: "100%", display: "grid", placeItems: "center" }}><CircularProgress aria-label={t("people.org.loading")} /></Box>
        ) : (
          <svg ref={svgRef} width="100%" height="100%" style={{ display: "block", touchAction: "none" }}>
            <g transform={`translate(${transform.x},${transform.y}) scale(${transform.k})`}>
              {layout?.links.map((l) => {
                const s = l.source as HierarchyPointNode<Datum>;
                const d = l.target as HierarchyPointNode<Datum>;
                const midY = s.y + H + GAP_Y / 2;
                return <path key={`${s.data.id}-${d.data.id}`} d={`M${s.x},${s.y + H} V${midY} H${d.x} V${d.y}`} fill="none" stroke={f.line} strokeWidth={2} />;
              })}
              {layout?.nodes.map((n) => {
                const it = items[n.data.id];
                if (!it) return null;
                return (
                  <foreignObject key={it.id} x={n.x - W / 2} y={n.y} width={W} height={H} style={{ overflow: "visible" }}>
                    <NodeCard item={it} loading={loadingIds.has(it.id)} reduced={reduced} onToggle={() => toggle(it.id)} />
                  </foreignObject>
                );
              })}
            </g>
          </svg>
        )}
      </Box>
      <Typography id="org-keys" sx={{ fontSize: 12, color: f.muted, mt: 1 }}>{t("people.org.keys")}</Typography>
    </Box>
  );
}

function NodeCard({ item, loading, reduced, onToggle }: { item: Item; loading: boolean; reduced: boolean; onToggle: () => void }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const holder = item.holders?.[0];
  const more = (item.holders?.length ?? 0) - 1;
  const kids = item.children?.length ?? item.children_count ?? 0;
  return (
    <Box
      sx={{
        width: W, height: H, boxSizing: "border-box", p: 1.25, borderRadius: "14px", bgcolor: f.surface, boxShadow: f.shadow,
        border: `1px solid ${item.is_critical ? f.sun : f.line}`, display: "flex", flexDirection: "column", gap: 0.5,
        transition: reduced ? "none" : "box-shadow 160ms ease", "&:hover": { boxShadow: f.shadowHover }, fontFamily: "inherit",
      }}
    >
      <Stack direction="row" spacing={1} alignItems="center" sx={{ minWidth: 0 }}>
        {holder ? <UserAvatar name={holder.name} src={holder.photo_url} size={40} /> : (
          <Box sx={{ width: 40, height: 40, borderRadius: "12px", bgcolor: f.surface2, border: `1px dashed ${f.line}`, display: "grid", placeItems: "center", flexShrink: 0 }}>
            <Emoji name="seedling" size={20} />
          </Box>
        )}
        <Box sx={{ minWidth: 0, flex: 1 }}>
          {holder ? (
            <Link component={RouterLink} to={`/employees/${holder.employee_id}`} underline="hover"
              sx={{ fontWeight: 800, fontSize: 14, color: f.ink, display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {holder.name}{more > 0 ? ` +${more}` : ""}
            </Link>
          ) : (
            <Typography sx={{ fontWeight: 700, fontSize: 14, color: f.muted }}>{t("people.org.vacant")}</Typography>
          )}
          <Typography sx={{ fontSize: 12, color: f.muted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={item.title}>{item.title}</Typography>
        </Box>
      </Stack>
      <Stack direction="row" alignItems="center" spacing={0.5} sx={{ mt: "auto", minWidth: 0 }}>
        <Typography sx={{ fontSize: 11, color: f.muted, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {[item.department, item.location].filter(Boolean).join(" · ")}
        </Typography>
        {item.is_critical && <StatusChip tone="sun" emoji="star" label={t("people.org.key_role")} />}
        {item.has_children && (
          <Button
            size="small"
            variant={item.open ? "contained" : "outlined"}
            onClick={onToggle}
            aria-expanded={item.open}
            aria-label={item.open ? t("people.org.hide_team_aria", { title: item.title }) : t("people.org.show_team_aria", { title: item.title })}
            sx={{ minWidth: 0, px: 1, py: 0, fontSize: 12, lineHeight: 1.8 }}
          >
            {loading ? <CircularProgress size={12} /> : `${item.open ? "▴" : "▾"} ${kids > 0 ? kids : ""}`.trim()}
          </Button>
        )}
      </Stack>
    </Box>
  );
}
