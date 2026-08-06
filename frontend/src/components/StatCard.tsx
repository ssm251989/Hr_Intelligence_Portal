import type { SvgIconComponent } from "@mui/icons-material";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

interface Props {
  label: string;
  value: string | number;
  icon?: SvgIconComponent;
  color?: string;
}

export default function StatCard({ label, value, icon: Icon, color }: Props) {
  return (
    <Card variant="outlined" sx={{ flex: "1 1 200px" }}>
      <CardContent>
        <Stack direction="row" spacing={1.5} alignItems="flex-start">
          {Icon && (
            <Box
              sx={{
                width: 40,
                height: 40,
                borderRadius: "50%",
                bgcolor: color ? `${color}1A` : "action.selected",
                color: color || "primary.main",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                flexShrink: 0,
              }}
            >
              <Icon fontSize="small" />
            </Box>
          )}
          <Box>
            <Typography variant="body2" color="text.secondary">
              {label}
            </Typography>
            <Typography variant="h3">{value}</Typography>
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
}
