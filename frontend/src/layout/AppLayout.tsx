import { useState } from "react";
import DashboardOutlinedIcon from "@mui/icons-material/DashboardOutlined";
import WorkOutlineIcon from "@mui/icons-material/WorkOutline";
import PeopleAltOutlinedIcon from "@mui/icons-material/PeopleAltOutlined";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import PlaylistAddCheckOutlinedIcon from "@mui/icons-material/PlaylistAddCheckOutlined";
import EventOutlinedIcon from "@mui/icons-material/EventOutlined";
import PaidOutlinedIcon from "@mui/icons-material/PaidOutlined";
import VerifiedUserOutlinedIcon from "@mui/icons-material/VerifiedUserOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import AssessmentOutlinedIcon from "@mui/icons-material/AssessmentOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import type { SvgIconComponent } from "@mui/icons-material";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Stack from "@mui/material/Stack";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "../auth/AuthContext";
import ConfirmDialog from "../components/ConfirmDialog";

const DRAWER_WIDTH = 240;

interface ModuleLink {
  label: string;
  path: string;
  icon: SvgIconComponent;
}

const MODULES: ModuleLink[] = [
  { label: "Overview", path: "/", icon: DashboardOutlinedIcon },
  { label: "Jobs", path: "/jobs", icon: WorkOutlineIcon },
  { label: "Candidates", path: "/candidates", icon: PeopleAltOutlinedIcon },
  { label: "Screening", path: "/screening", icon: FactCheckOutlinedIcon },
  { label: "Shortlisting", path: "/shortlisting", icon: PlaylistAddCheckOutlinedIcon },
  { label: "Interviews", path: "/interviews", icon: EventOutlinedIcon },
  { label: "Salary", path: "/salary", icon: PaidOutlinedIcon },
  { label: "BGV", path: "/bgv", icon: VerifiedUserOutlinedIcon },
  { label: "Offers", path: "/offers", icon: DescriptionOutlinedIcon },
  { label: "Reports", path: "/reports", icon: AssessmentOutlinedIcon },
  { label: "Settings", path: "/settings", icon: SettingsOutlinedIcon },
];

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [confirmLogoutOpen, setConfirmLogoutOpen] = useState(false);

  const handleLogout = () => {
    setConfirmLogoutOpen(false);
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <Box sx={{ display: "flex" }}>
      <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
        <Toolbar sx={{ justifyContent: "space-between" }}>
          <Typography variant="h6" noWrap component="div">
            HR Automation
          </Typography>
          <Stack direction="row" spacing={2} alignItems="center">
            {user && (
              <Stack direction="row" spacing={1} alignItems="center">
                <Typography variant="body2">{user.full_name || user.email}</Typography>
                <Chip label={user.role} size="small" color="secondary" />
              </Stack>
            )}
            <Button color="inherit" size="small" onClick={() => setConfirmLogoutOpen(true)}>
              Logout
            </Button>
          </Stack>
        </Toolbar>
      </AppBar>
      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          [`& .MuiDrawer-paper`]: { width: DRAWER_WIDTH, boxSizing: "border-box" },
        }}
      >
        <Toolbar />
        <Divider />
        <List>
          {MODULES.map(({ label, path, icon: Icon }) => (
            <ListItemButton
              key={path}
              component={NavLink}
              to={path}
              end={path === "/"}
              sx={{
                "&.active": {
                  backgroundColor: "action.selected",
                  borderRight: "3px solid",
                  borderColor: "primary.main",
                },
              }}
            >
              <ListItemIcon>
                <Icon />
              </ListItemIcon>
              <ListItemText primary={label} />
            </ListItemButton>
          ))}
        </List>
      </Drawer>
      <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
        <Toolbar />
        <Outlet />
      </Box>

      <ConfirmDialog
        open={confirmLogoutOpen}
        title="Log out?"
        message="You'll need to sign in again to continue."
        confirmLabel="Logout"
        destructive={false}
        onConfirm={handleLogout}
        onCancel={() => setConfirmLogoutOpen(false)}
      />
    </Box>
  );
}
