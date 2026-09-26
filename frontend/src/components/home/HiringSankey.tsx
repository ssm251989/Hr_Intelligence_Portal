import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { Layer, Rectangle, ResponsiveContainer, Sankey, Tooltip, type SankeyLinkProps, type SankeyNodeProps } from "recharts";

import type { HiringFlow } from "../../api/homeApi";
import { useT } from "../../i18n";

// L-V5: the hiring funnel as a Sankey. Forward flow in the brand colour, drop-outs in soft
// coral (with the legend saying so in words -- never colour alone).

const DROPS = new Set(["not_selected", "did_not_pass", "salary_declined", "checks_failed"]);

export default function HiringSankey({ flow, height = 240 }: { flow: HiringFlow; height?: number }) {
  const t = useT();
  const f = useTheme().palette.fresh;
  const data = {
    nodes: flow.nodes.map((n) => ({ name: t(`home.flow.${n.key}`), key: n.key })),
    links: flow.links,
  };
  const summary = flow.nodes
    .filter((n) => !DROPS.has(n.key))
    .map((n) => `${flow.stages[n.key] ?? 0} ${t(`home.flow.${n.key}`).toLowerCase()}`)
    .join(", ");

  const Node = (props: SankeyNodeProps) => {
    const { x, y, width, height: h, payload } = props;
    const drop = DROPS.has((payload as unknown as { key: string }).key);
    const value = (payload as unknown as { value?: number }).value ?? 0;
    return (
      <Layer>
        <Rectangle x={x} y={y} width={width} height={Math.max(h, 2)} fill={drop ? f.coral : f.brand} fillOpacity={drop ? 0.6 : 1} radius={3} />
        <text x={x + width + 6} y={y + h / 2} dy="0.35em" fontSize={12} fontWeight={700} fill={f.ink}>
          {payload.name} <tspan fill={f.muted} fontWeight={500}>{value}</tspan>
        </text>
      </Layer>
    );
  };

  const Link = (props: SankeyLinkProps) => {
    const { sourceX, targetX, sourceY, targetY, sourceControlX, targetControlX, linkWidth, payload } = props;
    const drop = DROPS.has((payload.target as unknown as { key: string }).key);
    return (
      <path
        d={`M${sourceX},${sourceY} C${sourceControlX},${sourceY} ${targetControlX},${targetY} ${targetX},${targetY}`}
        fill="none" stroke={drop ? f.coral : f.brand} strokeOpacity={drop ? 0.28 : 0.35} strokeWidth={Math.max(linkWidth, 1)}
      />
    );
  };

  return (
    <Box>
      <Box role="img" aria-label={t("home.flow.aria", { summary })} sx={{ width: "100%", height }}>
        <ResponsiveContainer width="100%" height="100%">
          <Sankey data={data} nodePadding={18} nodeWidth={10} margin={{ top: 8, right: 130, bottom: 8, left: 4 }} node={Node} link={Link} iterations={32}>
            <Tooltip />
          </Sankey>
        </ResponsiveContainer>
      </Box>
      <Stack direction="row" spacing={2} sx={{ mt: 1 }}>
        <Stack direction="row" spacing={0.75} alignItems="center">
          <Box sx={{ width: 12, height: 12, borderRadius: "3px", bgcolor: f.brand }} />
          <Typography variant="caption">{t("home.flow.forward")}</Typography>
        </Stack>
        <Stack direction="row" spacing={0.75} alignItems="center">
          <Box sx={{ width: 12, height: 12, borderRadius: "3px", bgcolor: f.coral, opacity: 0.6 }} />
          <Typography variant="caption">{t("home.flow.dropped")}</Typography>
        </Stack>
      </Stack>
    </Box>
  );
}
