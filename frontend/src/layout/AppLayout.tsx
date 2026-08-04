import WorkOutlineIcon from "@mui/icons-material/WorkOutline";
import PeopleAltOutlinedIcon from "@mui/icons-material/PeopleAltOutlined";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import PlaylistAddCheckOutlinedIcon from "@mui/icons-material/PlaylistAddCheckOutlined";
import EventOutlinedIcon from "@mui/icons-material/EventOutlined";
import PaidOutlinedIcon from "@mui/icons-material/PaidOutlined";
import VerifiedUserOutlinedIcon from "@mui/icons-material/VerifiedUserOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import AssessmentOutlinedIcon from "@mui/icons-material/AssessmentOutlined";
import type { SvgIconComponent } from "@mui/icons-material";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import { NavLink, Outlet } from "react-router-dom";

const DRAWER_WIDTH = 240;

interface ModuleLink {
  label: string;
  path: string;
  icon: SvgIconComponent;
}

const MODULES: ModuleLink[] = [
  { label: "Jobs", path: "/jobs", icon: WorkOutlineIcon },
  { label: "Candidates", path: "/candidates", icon: PeopleAltOutlinedIcon },
  { label: "Screening", path: "/screening", icon: FactCheckOutlinedIcon },
  { label: "Shortlisting", path: "/shortlisting", icon: PlaylistAddCheckOutlinedIcon },
  { label: "Interviews", path: "/interviews", icon: EventOutlinedIcon },
  { label: "Salary", path: "/salary", icon: PaidOutlinedIcon },
  { label: "BGV", path: "/bgv", icon: VerifiedUserOutlinedIcon },
  { label: "Offers", path: "/offers", icon: DescriptionOutlinedIcon },
  { label: "Reports", path: "/reports", icon: AssessmentOutlinedIcon },
];

export default function AppLayout() {
  return (
    <Box sx={{ display: "flex" }}>
      <AppBar position="fixed" sx={{ zIndex: (theme) => theme.zIndex.drawer + 1 }}>
        <Toolbar>
          <Typography variant="h6" noWrap component="div">
            HR Automation
          </Typography>
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
    </Box>
  );
}
