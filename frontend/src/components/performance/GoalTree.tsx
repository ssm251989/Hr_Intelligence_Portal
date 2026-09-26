import { useState } from "react";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import type { GoalNode } from "../../api/performanceExtra";
import { useT } from "../../i18n";
import { StatusChip, type Tone } from "../../ui-kit";
import { PerfChip, ProgressBar, useDateFormat, useFresh } from "./shared";

// F1: goals tree company > team > me. Every row can open/close with a button that says
// so (aria-expanded); progress always shows its number in words.

const LEVEL: Record<string, { tone: Tone; emoji: string }> = {
  company: { tone: "brand", emoji: "building" },
  department: { tone: "sky", emoji: "people" },
  team: { tone: "sky", emoji: "handshake" },
  individual: { tone: "sun", emoji: "target" },
};

function Node({ node, depth, open, toggle }: { node: GoalNode; depth: number; open: Set<string>; toggle: (id: string) => void }) {
  const t = useT();
  const f = useFresh();
  const date = useDateFormat();
  const hasKids = node.children.length > 0;
  const isOpen = open.has(node.id);
  const lvl = LEVEL[node.level] ?? LEVEL.individual;
  const shown = hasKids && !node.progress_pct && node.rolled_up_progress_pct != null ? node.rolled_up_progress_pct : node.progress_pct;
  const levelLabel = node.level === "individual" && node.is_mine ? t("performance.level.me") : t(`performance.level.${node.level}`);
  return (
    <Box component="li" role="treeitem" aria-expanded={hasKids ? isOpen : undefined} sx={{ listStyle: "none" }}>
      <Stack
        direction={{ xs: "column", md: "row" }}
        spacing={{ xs: 0.75, md: 1.5 }}
        alignItems={{ xs: "flex-start", md: "center" }}
        sx={{ py: 1.1, pl: { xs: depth * 1.5, md: depth * 3 }, pr: 1, borderBottom: `1px solid ${f.line}`, bgcolor: node.is_mine ? f.brandSoft : undefined, borderRadius: node.is_mine ? "10px" : 0 }}
      >
        <Stack direction="row" spacing={1} alignItems="center" sx={{ flex: 1, minWidth: 0 }}>
          {hasKids ? (
            <IconButton
              size="small"
              onClick={() => toggle(node.id)}
              aria-label={isOpen ? t("performance.tree.collapse", { title: node.title }) : t("performance.tree.expand", { title: node.title, count: node.children.length })}
            >
              {isOpen ? <ExpandMoreIcon fontSize="small" /> : <ChevronRightIcon fontSize="small" />}
            </IconButton>
          ) : (
            <Box sx={{ width: 30 }} />
          )}
          <StatusChip tone={lvl.tone} emoji={lvl.emoji} label={levelLabel} />
          <Box sx={{ minWidth: 0 }}>
            <Typography sx={{ fontWeight: 700 }} noWrap title={node.title}>{node.title}</Typography>
            <Typography sx={{ fontSize: 12, color: f.muted }}>
              {[node.owner_name, node.due_date ? t("performance.tree.due", { date: date(node.due_date) }) : null, hasKids ? t("performance.tree.children", { count: node.children.length }) : null]
                .filter(Boolean)
                .join(" · ")}
            </Typography>
          </Box>
        </Stack>
        <Stack direction="row" spacing={1} alignItems="center" sx={{ pl: { xs: 5, md: 0 } }}>
          <Box sx={{ width: 200 }}><ProgressBar value={shown} compact /></Box>
          {node.status === "completed" ? <PerfChip status="completed" /> : node.is_mine && node.checkin_due ? <PerfChip status="checkin_due" /> : null}
        </Stack>
      </Stack>
      {hasKids && isOpen && (
        <Box component="ul" role="group" sx={{ m: 0, p: 0 }}>
          {node.children.map((c) => <Node key={c.id} node={c} depth={depth + 1} open={open} toggle={toggle} />)}
        </Box>
      )}
    </Box>
  );
}

export default function GoalTree({ roots }: { roots: GoalNode[] }) {
  const t = useT();
  // Everything opens by default so "me" is visible under team and company at first glance.
  const all = new Set<string>();
  const walk = (n: GoalNode) => {
    if (n.children.length) all.add(n.id);
    n.children.forEach(walk);
  };
  roots.forEach(walk);
  const [open, setOpen] = useState<Set<string>>(all);
  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  return (
    <Box component="ul" role="tree" aria-label={t("performance.tree.title")} sx={{ m: 0, p: 0 }}>
      {roots.map((r) => <Node key={r.id} node={r} depth={0} open={open} toggle={toggle} />)}
    </Box>
  );
}

export function flattenGoals(roots: GoalNode[]): GoalNode[] {
  const out: GoalNode[] = [];
  const walk = (n: GoalNode) => {
    out.push(n);
    n.children.forEach(walk);
  };
  roots.forEach(walk);
  return out;
}
