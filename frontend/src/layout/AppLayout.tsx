import { useEffect, useRef, useState } from "react";
import AssessmentOutlinedIcon from "@mui/icons-material/AssessmentOutlined";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import DarkModeOutlinedIcon from "@mui/icons-material/DarkModeOutlined";
import DashboardOutlinedIcon from "@mui/icons-material/DashboardOutlined";
import DescriptionOutlinedIcon from "@mui/icons-material/DescriptionOutlined";
import EventOutlinedIcon from "@mui/icons-material/EventOutlined";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import LightModeOutlinedIcon from "@mui/icons-material/LightModeOutlined";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import NotificationsOutlinedIcon from "@mui/icons-material/NotificationsOutlined";
import PaidOutlinedIcon from "@mui/icons-material/PaidOutlined";
import PeopleAltOutlinedIcon from "@mui/icons-material/PeopleAltOutlined";
import PlaylistAddCheckOutlinedIcon from "@mui/icons-material/PlaylistAddCheckOutlined";
import SearchIcon from "@mui/icons-material/Search";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import VerifiedUserOutlinedIcon from "@mui/icons-material/VerifiedUserOutlined";
import WorkOutlineIcon from "@mui/icons-material/WorkOutline";
import type { SvgIconComponent } from "@mui/icons-material";
import Autocomplete from "@mui/material/Autocomplete";
import AppBar from "@mui/material/AppBar";
import Avatar from "@mui/material/Avatar";
import Badge from "@mui/material/Badge";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Collapse from "@mui/material/Collapse";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Popover from "@mui/material/Popover";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Toolbar from "@mui/material/Toolbar";
import Typography from "@mui/material/Typography";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { reportsApi } from "../api/client";
import type { RecentActivityItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import ConfirmDialog from "../components/ConfirmDialog";
import RecentActivityFeed from "../components/RecentActivityFeed";
import { useThemeMode } from "../theme/ThemeModeContext";

const DRAWER_WIDTH = 200;
const RAIL_WIDTH = 72;
const SIDEBAR_STORAGE_KEY = "hr-automation-sidebar-expanded";
const ACTIVITY_LAST_SEEN_KEY = "hr-automation-activity-last-seen";

interface ModuleChild {
  label: string;
  path: string;
}

interface ModuleLink {
  label: string;
  path: string;
  icon: SvgIconComponent;
  // Candidate Detail is a drill-down reached by clicking a row in the List sub-item, not
  // a fourth entry here -- these three are the only real destinations under Candidates.
  children?: ModuleChild[];
}

const MODULES: ModuleLink[] = [
  { label: "Overview", path: "/", icon: DashboardOutlinedIcon },
  { label: "Jobs", path: "/jobs", icon: WorkOutlineIcon },
  {
    label: "Candidates",
    path: "/candidates",
    icon: PeopleAltOutlinedIcon,
    children: [
      { label: "Dashboard", path: "/candidates/dashboard" },
      { label: "Candidates List", path: "/candidates/list" },
      { label: "Import from Source", path: "/candidates/import" },
    ],
  },
  {
    label: "Screening",
    path: "/screening",
    icon: FactCheckOutlinedIcon,
    children: [
      { label: "Dashboard", path: "/screening/dashboard" },
      { label: "Screening List", path: "/screening/list" },
    ],
  },
  { label: "Shortlisting", path: "/shortlisting", icon: PlaylistAddCheckOutlinedIcon },
  { label: "Interviews", path: "/interviews", icon: EventOutlinedIcon },
  { label: "Salary", path: "/salary", icon: PaidOutlinedIcon },
  { label: "BGV", path: "/bgv", icon: VerifiedUserOutlinedIcon },
  { label: "Offers", path: "/offers", icon: DescriptionOutlinedIcon },
  { label: "Reports", path: "/reports", icon: AssessmentOutlinedIcon },
  { label: "Settings", path: "/settings", icon: SettingsOutlinedIcon },
];

// Flattened for the "Jump to a module" search -- sub-items get a real, direct jump target
// too, not just their parent.
const SEARCHABLE_MODULES = MODULES.flatMap((module) => [
  { label: module.label, path: module.path },
  ...(module.children ?? []).map((child) => ({ label: `${module.label} — ${child.label}`, path: child.path })),
]);

function initials(nameOrEmail: string): string {
  const trimmed = nameOrEmail.trim();
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return trimmed.slice(0, 2).toUpperCase();
}

export default function AppLayout() {
  const { user, logout } = useAuth();
  const { mode, toggleMode } = useThemeMode();
  const navigate = useNavigate();
  const location = useLocation();
  const [confirmLogoutOpen, setConfirmLogoutOpen] = useState(false);
  const [activityAnchor, setActivityAnchor] = useState<HTMLElement | null>(null);
  const [activityItems, setActivityItems] = useState<RecentActivityItem[]>([]);
  // Real "unread" tracking: a timestamp (ms) of the last time the dropdown was opened,
  // persisted so it survives a reload. Never opened before -> 0, which makes every
  // currently-fetched item count as unread (same total the old static activityCount gave
  // on first-ever load), not an arbitrary "nothing is unread" default.
  const [lastSeenAt, setLastSeenAt] = useState<number>(() => {
    const stored = window.localStorage.getItem(ACTIVITY_LAST_SEEN_KEY);
    return stored ? Number(stored) : 0;
  });
  const [expanded, setExpanded] = useState(() => {
    const stored = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
    return stored === null ? true : stored === "true";
  });

  // Real, independent open/closed state per parent module (keyed by its path) -- collapsed
  // by default. This is intentionally separate from "which section's route is currently
  // active": that's used only to decide *when to auto-expand*, never to compute the
  // rendered open/closed state directly, so a manual collapse sticks while navigating
  // between that section's own sub-pages.
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({});
  const toggleSection = (path: string) =>
    setOpenSections((prev) => ({ ...prev, [path]: !prev[path] }));

  // The parent module (if any) whose section the current route falls under -- null outside
  // any such section. Moving between sibling sub-pages (e.g. Dashboard -> List) yields the
  // same value here, so the auto-expand effect below only fires on actually *entering* or
  // *leaving* a section, not on every in-section navigation.
  const activeParentPath = MODULES.find((module) => module.children && location.pathname.startsWith(module.path))?.path ?? null;

  // Previous render's activeParentPath -- lets the effect below tell "just entered/left a
  // section" apart from "still inside the same section" (a sibling-to-sibling navigation,
  // where activeParentPath doesn't change at all and the effect must NOT re-fire).
  const prevActiveParentPathRef = useRef<string | null>(null);

  useEffect(() => {
    const prev = prevActiveParentPathRef.current;
    if (prev !== activeParentPath) {
      setOpenSections((prevSections) => {
        const next = { ...prevSections };
        // Leaving a section entirely (including a full-page load that lands outside any
        // section, where prev is already null) collapses it back down -- AppLayout never
        // remounts on client-side navigation, so without this a section auto-expanded once
        // stays stuck open in openSections for the rest of the SPA session even after
        // browsing away to an unrelated module.
        if (prev) next[prev] = false;
        // Entering a section from outside it auto-expands it. Moving between that same
        // section's own sub-pages never reaches this branch (prev === activeParentPath),
        // so a manual collapse while already inside the section sticks.
        if (activeParentPath) next[activeParentPath] = true;
        return next;
      });
    }
    prevActiveParentPathRef.current = activeParentPath;
  }, [activeParentPath]);

  useEffect(() => {
    reportsApi
      .recentActivity(9)
      .then((res) => setActivityItems(res.items))
      .catch(() => setActivityItems([]));
  }, []);

  const unreadActivityCount = activityItems.filter(
    (item) => new Date(item.created_at).getTime() > lastSeenAt,
  ).length;

  const handleOpenActivity = (event: { currentTarget: HTMLElement }) => {
    setActivityAnchor(event.currentTarget);
    const now = Date.now();
    setLastSeenAt(now);
    window.localStorage.setItem(ACTIVITY_LAST_SEEN_KEY, String(now));
  };

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(expanded));
  }, [expanded]);

  const handleLogout = () => {
    setConfirmLogoutOpen(false);
    logout();
    navigate("/login", { replace: true });
  };

  const drawerWidth = expanded ? DRAWER_WIDTH : RAIL_WIDTH;

  return (
    <Box sx={{ display: "flex" }}>
      <AppBar
        position="fixed"
        color="default"
        sx={{ zIndex: (theme) => theme.zIndex.drawer + 1, bgcolor: "background.paper" }}
      >
        <Toolbar sx={{ justifyContent: "space-between", gap: 2 }}>
          <Stack direction="row" spacing={1.5} alignItems="center" sx={{ flexShrink: 0 }}>
            <Box
              sx={{
                width: 32,
                height: 32,
                borderRadius: "10px",
                bgcolor: "primary.main",
                color: "primary.contrastText",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 700,
                fontSize: 13,
                flexShrink: 0,
              }}
            >
              CTD
            </Box>
            <Box sx={{ display: { xs: "none", sm: "block" } }}>
              <Typography variant="subtitle1" fontWeight={700} lineHeight={1.1}>
                CTD Techs
              </Typography>
              <Typography variant="caption" color="text.secondary" lineHeight={1}>
                HR Automation
              </Typography>
            </Box>
          </Stack>

          {/* Real navigation, not a decorative search box -- filters MODULES by label and
              jumps straight to the matching page. A full cross-entity search would need a
              backend index this app doesn't have; this is the honest scope for now. */}
          <Autocomplete
            options={SEARCHABLE_MODULES}
            getOptionLabel={(option) => option.label}
            onChange={(_event, value) => value && navigate(value.path)}
            blurOnSelect
            clearOnBlur
            size="small"
            sx={{ width: 260, display: { xs: "none", md: "block" } }}
            renderInput={(params) => (
              <TextField
                {...params}
                placeholder="Jump to a module..."
                slotProps={{
                  input: {
                    ...params.InputProps,
                    startAdornment: <SearchIcon fontSize="small" sx={{ color: "text.secondary", mr: 0.5 }} />,
                  },
                }}
              />
            )}
          />

          <Stack direction="row" spacing={0.5} alignItems="center" sx={{ flexShrink: 0 }}>
            <Tooltip title={mode === "dark" ? "Switch to light mode" : "Switch to dark mode"}>
              <IconButton color="inherit" onClick={toggleMode} aria-label="Toggle color mode">
                {mode === "dark" ? <LightModeOutlinedIcon /> : <DarkModeOutlinedIcon />}
              </IconButton>
            </Tooltip>
            <IconButton color="inherit" onClick={handleOpenActivity} aria-label="Recent activity">
              <Badge badgeContent={unreadActivityCount} color="secondary" max={9}>
                <NotificationsOutlinedIcon />
              </Badge>
            </IconButton>
          </Stack>
        </Toolbar>
      </AppBar>
      <Drawer
        variant="permanent"
        sx={{
          width: drawerWidth,
          flexShrink: 0,
          whiteSpace: "nowrap",
          [`& .MuiDrawer-paper`]: {
            width: drawerWidth,
            boxSizing: "border-box",
            overflowX: "hidden",
            transition: (theme) => theme.transitions.create("width", { duration: 220 }),
            display: "flex",
            flexDirection: "column",
          },
        }}
      >
        <Toolbar />
        <Box sx={{ display: "flex", justifyContent: expanded ? "flex-end" : "center", px: 1, py: 0.5 }}>
          <Tooltip title={expanded ? "Collapse sidebar" : "Expand sidebar"}>
            <IconButton size="small" onClick={() => setExpanded((prev) => !prev)}>
              {expanded ? <ChevronLeftIcon fontSize="small" /> : <ChevronRightIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Box>
        <Divider />
        <List sx={{ flexGrow: 1 }}>
          {MODULES.map(({ label, path, icon: Icon, children }) => {
            const isSectionRoute = activeParentPath === path;
            const isOpen = Boolean(children) && Boolean(openSections[path]);

            // With children AND room to show them (rail expanded): the row is a pure
            // disclosure toggle, not a navigation link -- there's no standalone page for
            // "Candidates" itself to navigate to that would be distinct from expanding it.
            // In the icon-only rail, there's no room to show sub-items at all, so it falls
            // back to a normal NavLink (like every leaf item) so the icon still does
            // something useful.
            const activeSx = {
              backgroundColor: "action.selected",
              borderRight: "3px solid",
              borderColor: "primary.main",
            };
            const item =
              children && expanded ? (
                <ListItemButton
                  key={path}
                  onClick={() => toggleSection(path)}
                  sx={{
                    justifyContent: "flex-start",
                    px: 2,
                    transition: "background-color 180ms ease",
                    ...(isSectionRoute ? activeSx : {}),
                  }}
                >
                  <ListItemIcon sx={{ minWidth: 40, justifyContent: "center" }}>
                    <Icon />
                  </ListItemIcon>
                  <ListItemText primary={label} />
                  {isOpen ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                </ListItemButton>
              ) : (
                <ListItemButton
                  key={path}
                  component={NavLink}
                  to={path}
                  end={path === "/"}
                  sx={{
                    justifyContent: expanded ? "flex-start" : "center",
                    px: expanded ? 2 : 1.5,
                    transition: "background-color 180ms ease",
                    "&.active": activeSx,
                  }}
                >
                  <ListItemIcon sx={{ minWidth: expanded ? 40 : "auto", justifyContent: "center" }}>
                    <Icon />
                  </ListItemIcon>
                  {expanded && <ListItemText primary={label} />}
                </ListItemButton>
              );
            const wrapped = expanded ? (
              item
            ) : (
              <Tooltip key={path} title={label} placement="right">
                <span>{item}</span>
              </Tooltip>
            );
            if (!children) {
              return wrapped;
            }
            return (
              <Box key={path}>
                {wrapped}
                {expanded && (
                  <Collapse in={isOpen} timeout="auto" unmountOnExit>
                    <List disablePadding>
                      {children.map((child) => (
                        <ListItemButton
                          key={child.path}
                          component={NavLink}
                          to={child.path}
                          sx={{
                            pl: 5,
                            py: 0.75,
                            "&.active": activeSx,
                          }}
                        >
                          <ListItemText primary={child.label} slotProps={{ primary: { variant: "body2" } }} />
                        </ListItemButton>
                      ))}
                    </List>
                  </Collapse>
                )}
              </Box>
            );
          })}
        </List>

        {/* Sidebar user footer -- replaces the name/role/logout that used to live in the
            top AppBar. Collapses to just an avatar (with the same info on hover, and
            logout still one click away) when the rail is collapsed. */}
        <Divider />
        {user && (
          <Box sx={{ p: expanded ? 1.5 : 1, py: 1.5 }}>
            <Stack
              direction="row"
              spacing={1.25}
              alignItems="center"
              justifyContent={expanded ? "flex-start" : "center"}
            >
              <Tooltip title={expanded ? "" : `${user.full_name || user.email} (${user.role})`}>
                <Avatar sx={{ width: 32, height: 32, bgcolor: "primary.main", fontSize: 13 }}>
                  {initials(user.full_name || user.email)}
                </Avatar>
              </Tooltip>
              {expanded && (
                <>
                  <Box sx={{ minWidth: 0, flexGrow: 1 }}>
                    <Typography variant="body2" noWrap fontWeight={600}>
                      {user.full_name || user.email}
                    </Typography>
                    <Chip label={user.role} size="small" sx={{ height: 18, fontSize: 11 }} />
                  </Box>
                  <Tooltip title="Log out">
                    <IconButton size="small" onClick={() => setConfirmLogoutOpen(true)} aria-label="Log out">
                      <LogoutOutlinedIcon fontSize="small" />
                    </IconButton>
                  </Tooltip>
                </>
              )}
            </Stack>
            {!expanded && (
              <Stack alignItems="center" mt={0.5}>
                <IconButton size="small" onClick={() => setConfirmLogoutOpen(true)} aria-label="Log out">
                  <LogoutOutlinedIcon fontSize="small" />
                </IconButton>
              </Stack>
            )}
          </Box>
        )}
      </Drawer>
      <Box component="main" sx={{ flexGrow: 1, p: 3, minWidth: 0 }}>
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

      <Popover
        open={Boolean(activityAnchor)}
        anchorEl={activityAnchor}
        onClose={() => setActivityAnchor(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "right" }}
        transformOrigin={{ vertical: "top", horizontal: "right" }}
      >
        <Box sx={{ width: 340, p: 2 }}>
          <Typography variant="subtitle1" mb={1}>
            Recent Activity
          </Typography>
          <RecentActivityFeed limit={10} dense />
        </Box>
      </Popover>
    </Box>
  );
}
