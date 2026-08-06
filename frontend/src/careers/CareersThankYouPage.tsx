import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import { Link as RouterLink } from "react-router-dom";

export default function CareersThankYouPage() {
  return (
    <Box textAlign="center" py={6}>
      <Typography variant="h4" fontWeight={700} mb={2}>
        Thank you for applying!
      </Typography>
      <Typography variant="body1" color="text.secondary" mb={4}>
        We've received your application and our team will review it shortly. If you're a good fit, we'll be
        in touch by email.
      </Typography>
      <Button component={RouterLink} to="/careers" variant="contained">
        View more open positions
      </Button>
    </Box>
  );
}
