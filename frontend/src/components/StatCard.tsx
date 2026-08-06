import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Typography from "@mui/material/Typography";

export default function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Card variant="outlined" sx={{ flex: "1 1 200px" }}>
      <CardContent>
        <Typography variant="body2" color="text.secondary">
          {label}
        </Typography>
        <Typography variant="h3">{value}</Typography>
      </CardContent>
    </Card>
  );
}
