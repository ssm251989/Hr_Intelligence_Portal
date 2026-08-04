import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";

export default function ComingSoonPage({ title }: { title: string }) {
  return (
    <Box>
      <Typography variant="h4" gutterBottom>
        {title}
      </Typography>
      <Typography color="text.secondary">Coming soon.</Typography>
    </Box>
  );
}
