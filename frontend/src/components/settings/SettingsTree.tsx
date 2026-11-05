import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { Emoji } from "../../ui-kit";

export interface TreeLeaf {
  id: string;
  label: string;
  emoji: string;
}

export interface TreeGroup {
  id: string;
  label: string;
  items: TreeLeaf[];
}

type Node = { kind: "group"; group: TreeGroup } | { kind: "leaf"; leaf: TreeLeaf; groupId: string };

// Part 15.4 Settings (A1): the category tree on the left. WAI-ARIA tree pattern: one tab
// stop (roving tabindex), Up/Down move, Right opens a group / steps into it, Left closes
// it / steps back to the group, Home/End jump, Enter or Space picks.
export default function SettingsTree({
  groups, selected, onSelect, label, forceExpanded,
}: {
  groups: TreeGroup[];
  selected: string;
  onSelect: (id: string) => void;
  label: string;
  /** While searching every group with a match stays open. */
  forceExpanded?: boolean;
}) {
  const f = useTheme().palette.fresh;
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [focusId, setFocusId] = useState<string>(selected);
  const refs = useRef<Map<string, HTMLElement>>(new Map());

  const isOpen = (g: string) => forceExpanded || !collapsed[g];

  const nodes = useMemo<Node[]>(() => {
    const out: Node[] = [];
    for (const group of groups) {
      out.push({ kind: "group", group });
      if (forceExpanded || !collapsed[group.id]) for (const leaf of group.items) out.push({ kind: "leaf", leaf, groupId: group.id });
    }
    return out;
  }, [groups, collapsed, forceExpanded]);

  const nodeId = (n: Node) => (n.kind === "group" ? `group:${n.group.id}` : n.leaf.id);

  // Keep the tab stop on something that exists (the picked category, else the first node).
  useEffect(() => {
    if (!nodes.some((n) => nodeId(n) === focusId)) setFocusId(nodes.some((n) => nodeId(n) === selected) ? selected : nodes[0] ? nodeId(nodes[0]) : "");
  }, [nodes, focusId, selected]);

  const move = (id: string) => {
    setFocusId(id);
    refs.current.get(id)?.focus();
  };

  const onKeyDown = (e: KeyboardEvent, node: Node) => {
    const idx = nodes.findIndex((n) => nodeId(n) === nodeId(node));
    const go = (i: number) => nodes[i] && move(nodeId(nodes[i]));
    switch (e.key) {
      case "ArrowDown":
        go(idx + 1);
        break;
      case "ArrowUp":
        go(idx - 1);
        break;
      case "Home":
        go(0);
        break;
      case "End":
        go(nodes.length - 1);
        break;
      case "ArrowRight":
        if (node.kind === "group") {
          if (!isOpen(node.group.id)) setCollapsed((c) => ({ ...c, [node.group.id]: false }));
          else go(idx + 1);
        }
        break;
      case "ArrowLeft":
        if (node.kind === "leaf") move(`group:${node.groupId}`);
        else if (isOpen(node.group.id) && !forceExpanded) setCollapsed((c) => ({ ...c, [node.group.id]: true }));
        break;
      case "Enter":
      case " ":
        if (node.kind === "leaf") onSelect(node.leaf.id);
        else if (!forceExpanded) setCollapsed((c) => ({ ...c, [node.group.id]: isOpen(node.group.id) }));
        break;
      default:
        return;
    }
    e.preventDefault();
  };

  const setRef = (id: string) => (el: HTMLElement | null) => {
    if (el) refs.current.set(id, el);
    else refs.current.delete(id);
  };

  const focusRing = { outline: `2px solid ${f.brand}`, outlineOffset: 2 };

  return (
    <Box component="ul" role="tree" aria-label={label} sx={{ listStyle: "none", m: 0, p: 0, display: "flex", flexDirection: "column", gap: 0.25 }}>
      {groups.map((group) => {
        const gid = `group:${group.id}`;
        const open = isOpen(group.id);
        const groupNode: Node = { kind: "group", group };
        return (
          <Box component="li" key={group.id} role="treeitem" aria-expanded={open} aria-selected={false}
            ref={setRef(gid)} tabIndex={focusId === gid ? 0 : -1}
            onKeyDown={(e: KeyboardEvent) => e.target === e.currentTarget && onKeyDown(e, groupNode)}
            onFocus={(e) => e.target === e.currentTarget && setFocusId(gid)}
            sx={{ outline: "none", "&:focus-visible > .tree-group-label": focusRing }}
          >
            <Box
              className="tree-group-label"
              onClick={() => !forceExpanded && setCollapsed((c) => ({ ...c, [group.id]: open }))}
              sx={{ display: "flex", alignItems: "center", gap: 0.75, px: 1.25, pt: 1.5, pb: 0.5, cursor: forceExpanded ? "default" : "pointer", borderRadius: "8px", userSelect: "none" }}
            >
              <Box component="span" aria-hidden sx={{ fontSize: 10, color: f.muted, width: 10, transform: open ? "rotate(90deg)" : "none", transition: "transform 160ms ease", "@media (prefers-reduced-motion: reduce)": { transition: "none" }, ".reduce-motion &": { transition: "none" } }}>
                ▶
              </Box>
              <Typography component="span" sx={{ color: f.muted, fontSize: 11, fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase" }}>
                {group.label}
              </Typography>
            </Box>
            {open && (
              <Box component="ul" role="group" sx={{ listStyle: "none", m: 0, p: 0, display: "flex", flexDirection: "column", gap: 0.25 }}>
                {group.items.map((leaf) => {
                  const active = leaf.id === selected;
                  const node: Node = { kind: "leaf", leaf, groupId: group.id };
                  return (
                    <Box
                      component="li"
                      key={leaf.id}
                      role="treeitem"
                      aria-selected={active}
                      aria-current={active ? "page" : undefined}
                      ref={setRef(leaf.id)}
                      tabIndex={focusId === leaf.id ? 0 : -1}
                      onKeyDown={(e: KeyboardEvent) => onKeyDown(e, node)}
                      onFocus={() => setFocusId(leaf.id)}
                      onClick={() => {
                        setFocusId(leaf.id);
                        onSelect(leaf.id);
                      }}
                      data-testid={`settings-category-${leaf.id}`}
                      sx={{
                        display: "flex", alignItems: "center", gap: 1.25, px: 1.25, py: 1, borderRadius: "10px", cursor: "pointer",
                        color: active ? f.brand : f.ink, bgcolor: active ? f.brandSoft : "transparent", fontWeight: active ? 700 : 500,
                        transition: "background-color 160ms ease", "&:hover": { bgcolor: active ? f.brandSoft : f.surface2 },
                        "&:focus-visible": focusRing, outline: "none",
                      }}
                    >
                      <Emoji name={leaf.emoji} size={18} />
                      <Box component="span" sx={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis" }}>{leaf.label}</Box>
                    </Box>
                  );
                })}
              </Box>
            )}
          </Box>
        );
      })}
    </Box>
  );
}
