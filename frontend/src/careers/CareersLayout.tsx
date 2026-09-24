import Box from "@mui/material/Box";
import Container from "@mui/material/Container";
import Typography from "@mui/material/Typography";
import { Link as RouterLink, Outlet } from "react-router-dom";

import { useBootstrap } from "../bootstrap/BootstrapContext";

export default function CareersLayout() {
  const { productName } = useBootstrap();
  const careersSiteTitle = `${productName} Careers`;

  return (
    <Box sx={{ minHeight: "100vh", display: "flex", flexDirection: "column", bgcolor: "background.default" }}>
      <Box component="header" sx={{ borderBottom: 1, borderColor: "divider", bgcolor: "background.paper" }}>
        <Container maxWidth="md" sx={{ py: 2.5 }}>
          <Typography
            variant="h6"
            component={RouterLink}
            to="/careers"
            sx={{ textDecoration: "none", color: "text.primary", fontWeight: 700 }}
          >
            {careersSiteTitle}
          </Typography>
        </Container>
      </Box>

      <Container maxWidth="md" sx={{ py: 5, flex: 1 }}>
        <Outlet />
      </Container>

      <Box component="footer" sx={{ borderTop: 1, borderColor: "divider", py: 3 }}>
        <Container maxWidth="md">
          <Typography variant="body2" color="text.secondary" align="center">
            © {new Date().getFullYear()} {productName}. All rights reserved.
          </Typography>
        </Container>
      </Box>
    </Box>
  );
}
