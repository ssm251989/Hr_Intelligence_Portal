import { useEffect, useMemo, useState } from "react";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import DarkModeOutlinedIcon from "@mui/icons-material/DarkModeOutlined";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import LightModeOutlinedIcon from "@mui/icons-material/LightModeOutlined";
import LogoutOutlinedIcon from "@mui/icons-material/LogoutOutlined";
import MenuIcon from "@mui/icons-material/Menu";
import NotificationsOutlinedIcon from "@mui/icons-material/NotificationsOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import TranslateOutlinedIcon from "@mui/icons-material/TranslateOutlined";
import CheckIcon from "@mui/icons-material/Check";
import Avatar from "@mui/material/Avatar";
import Badge from "@mui/material/Badge";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Collapse from "@mui/material/Collapse";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Popover from "@mui/material/Popover";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";

import { brandingApi, experienceApi, reportsApi, type NavEntry, type NotificationGroup } from "../api/client";
import type { RecentActivityItem } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { useBootstrap } from "../bootstrap/BootstrapContext";
import { useMeBootstrap } from "../bootstrap/MeBootstrapContext";
import ConfirmDialog from "../components/ConfirmDialog";
import CopilotWidget from "../components/CopilotWidget";
import GlobalSearch from "../components/GlobalSearch";
import ModuleTour from "../components/ModuleTour";
import RecentActivityFeed from "../components/RecentActivityFeed";
import { LOCALES, useI18n, useT } from "../i18n";
import { useThemeMode } from "../theme/ThemeModeContext";
import Emoji from "../ui-kit/Emoji";
import {
  FALLBACK_NAV, NAV_CHILDREN, NAV_GROUP_ORDER, NOTIFICATION_MODULES, sectionOf, type NavGroup,
} from "./navConfig";

const SIDEBAR_WIDTH = 236;
const RAIL_WIDTH = 76;
const SIDEBAR_STORAGE_KEY = "hr-automation-sidebar-expanded";
const SEEN_KEY = "hr-automation-activity-last-seen";

function readStorage(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function writeStorage(key: string, value: string) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // per-visit only
  }
}

function initials(nameOrEmail: string): string {
  const parts = nameOrEmail.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return nameOrEmail.trim().slice(0, 2).toUpperCase();
}

interface ShellItem {
  label: string;
  path: string;
  icon: string;
  group: NavGroup;
  children?: { label: string; path: string }[];
}

function useShellNav(): ShellItem[] {
  const { data } = useMeBootstrap();
  const t = useT();
  return useMemo(() => {
    const nav: NavEntry[] = data?.nav?.length ? data.nav : FALLBACK_NAV;
    // t() already layers the company's renames (bootstrap.custom_labels) over en/hi/ta.
    const label = (key: string) => {
      const text = t(key);
      return text === key ? key.replace(/^nav\./, "").replace(/_/g, " ") : text;
    };
    return nav.map((n) => ({
      label: label(n.label_key),
      path: n.path,
      icon: n.icon ?? "puzzle",
      group: n.group ?? "today",
      children: NAV_CHILDREN[sectionOf(n.path)]?.map((c) => ({ label: t(c.labelKey), path: c.path })),
    }));
  }, [data, t]);
}

function isActive(item: ShellItem, pathname: string, hash: string): boolean {
  const [base, frag] = item.path.split("#");
  if (frag) return pathname === base && hash === `#${frag}`;
  if (item.path === "/") return pathname === "/";
  const section = sectionOf(item.path);
  return pathname === base || pathname.startsWith(section + "/") || pathname === section;
}

function Sidebar({ items, expanded, onToggle, onNavigate }: { items: ShellItem[]; expanded: boolean; onToggle?: () => void; onNavigate?: () => void }) {
  const theme = useTheme();
  const t = theme.palette.fresh;
  const tr = useT();
  const location = useLocation();
  const { productName, logoMark } = useBootstrap();
  const activeSection = sectionOf(location.pathname);
  const [open, setOpen] = useState<Record<string, boolean>>({});

  // Entering a section opens its sub-pages; a manual collapse sticks while inside it.
  useEffect(() => {
    if (NAV_CHILDREN[activeSection]) setOpen((prev) => (prev[activeSection] === undefined ? { ...prev, [activeSection]: true } : prev));
  }, [activeSection]);

  const itemSx = (active: boolean) => ({
    display: "flex", alignItems: "center", gap: 1.25, width: "100%", px: expanded ? 1.25 : 0, py: 1.1,
    justifyContent: expanded ? "flex-start" : "center", borderRadius: "10px", color: active ? t.brand : t.ink,
    bgcolor: active ? t.brandSoft : "transparent", fontWeight: active ? 700 : 500, fontSize: 14, textDecoration: "none",
    border: 0, font: "inherit", cursor: "pointer", textAlign: "left" as const, transition: "background-color 160ms ease",
    "&:hover": { bgcolor: active ? t.brandSoft : t.surface2 },
    "&:focus-visible": { outline: `2px solid ${t.brand}`, outlineOffset: 2 },
  });

  return (
    <Box
      component="aside"
      sx={{
        bgcolor: t.surface, borderRadius: "18px", boxShadow: t.shadow, p: expanded ? "16px 12px" : "16px 8px",
        display: "flex", flexDirection: "column", gap: 0.5, height: "100%", minHeight: 0,
      }}
    >
      <Stack direction="row" alignItems="center" spacing={1.25} sx={{ px: expanded ? 1 : 0, pb: 1.5, justifyContent: expanded ? "flex-start" : "center" }}>
        <Box sx={{ width: 34, height: 34, borderRadius: "10px", bgcolor: t.brand, color: t.brandInk, display: "grid", placeItems: "center", fontWeight: 800, fontSize: 13, flexShrink: 0 }}>
          {logoMark}
        </Box>
        {expanded && (
          <Typography noWrap sx={{ fontWeight: 800, fontSize: 16, flex: 1, minWidth: 0 }} title={productName}>
            {productName}
          </Typography>
        )}
      </Stack>

      <Box component="nav" aria-label="Main" sx={{ flex: 1, minHeight: 0, overflowY: "auto", overflowX: "hidden", display: "flex", flexDirection: "column", gap: 0.25 }}>
        {NAV_GROUP_ORDER.map((group) => {
          const groupItems = items.filter((i) => i.group === group);
          if (!groupItems.length) return null;
          return (
            <Box key={group} sx={{ display: "flex", flexDirection: "column", gap: 0.25 }}>
              {expanded ? (
                <Typography component="div" sx={{ m: "12px 10px 4px", color: t.muted, fontSize: 11, fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase" }}>
                  {tr(`nav.group.${group}`)}
                </Typography>
              ) : (
                <Divider sx={{ my: 1, mx: 1.5 }} />
              )}
              {groupItems.map((item) => {
                const active = isActive(item, location.pathname, location.hash);
                const section = sectionOf(item.path);
                const hasChildren = Boolean(item.children) && expanded;
                const isOpen = hasChildren && Boolean(open[section]);
                const row = hasChildren ? (
                  <Box component="button" type="button" aria-expanded={isOpen} onClick={() => setOpen((p) => ({ ...p, [section]: !p[section] }))} sx={itemSx(active)}>
                    <Emoji name={item.icon} size={18} />
                    <Box component="span" sx={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.label}</Box>
                    {isOpen ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
                  </Box>
                ) : (
                  <Box component={NavLink} to={item.path} end={item.path === "/"} onClick={onNavigate} aria-current={active ? "page" : undefined} sx={itemSx(active)}>
                    <Emoji name={item.icon} size={18} />
                    {expanded && <Box component="span" sx={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.label}</Box>}
                  </Box>
                );
                return (
                  <Box key={item.path}>
                    {expanded ? row : <Tooltip title={item.label} placement="right">{row}</Tooltip>}
                    {hasChildren && (
                      <Collapse in={isOpen} timeout="auto" unmountOnExit>
                        <Box sx={{ display: "flex", flexDirection: "column", gap: 0.25, py: 0.25, pl: 4.5 }}>
                          {item.children!.map((child) => {
                            const childActive = location.pathname === child.path;
                            return (
                              <Box key={child.path} component={NavLink} to={child.path} onClick={onNavigate} aria-current={childActive ? "page" : undefined}
                                sx={{ ...itemSx(childActive), py: 0.75, fontSize: 13, bgcolor: childActive ? t.brandSoft : "transparent" }}>
                                {child.label}
                              </Box>
                            );
                          })}
                        </Box>
                      </Collapse>
                    )}
                  </Box>
                );
              })}
            </Box>
          );
        })}
      </Box>

      {onToggle && (
        <Box sx={{ display: "flex", justifyContent: expanded ? "flex-end" : "center", pt: 1 }}>
          <Tooltip title={expanded ? tr("shell.menu_collapse") : tr("shell.menu_expand")}>
            <IconButton size="small" onClick={onToggle} aria-label={expanded ? tr("shell.menu_collapse") : tr("shell.menu_expand")}>
              {expanded ? <ChevronLeftIcon fontSize="small" /> : <ChevronRightIcon fontSize="small" />}
            </IconButton>
          </Tooltip>
        </Box>
      )}
    </Box>
  );
}

function NotificationsBell() {
  const t = useTheme().palette.fresh;
  const tr = useT();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const [groups, setGroups] = useState<NotificationGroup[]>([]);
  const [activity, setActivity] = useState<RecentActivityItem[]>([]);
  // Unread = anything newer than the last time the bell was opened (persisted per browser).
  const [lastSeenAt, setLastSeenAt] = useState<number>(() => Number(readStorage(SEEN_KEY) ?? 0));

  useEffect(() => {
    brandingApi.myNotifications().then((r) => setGroups(r.groups)).catch(() => setGroups([]));
    reportsApi.recentActivity(9).then((r) => setActivity(r.items)).catch(() => setActivity([]));
  }, []);

  const newer = (iso: string | null) => (iso ? new Date(iso).getTime() > lastSeenAt : false);
  const unread = groups.reduce((n, g) => n + g.items.filter((i) => newer(i.created_at)).length, 0) + activity.filter((a) => newer(a.created_at)).length;

  const open = (e: { currentTarget: HTMLElement }) => {
    setAnchor(e.currentTarget);
    const now = Date.now();
    setLastSeenAt(now);
    writeStorage(SEEN_KEY, String(now));
  };

  return (
    <>
      <Tooltip title={tr("shell.notifications")}>
        <IconButton onClick={open} aria-label={unread ? tr("shell.notifications_new", { count: unread }) : tr("shell.notifications")} sx={{ bgcolor: t.surface, border: `1px solid ${t.line}` }}>
          <Badge badgeContent={unread} color="secondary" max={9}>
            <NotificationsOutlinedIcon fontSize="small" />
          </Badge>
        </IconButton>
      </Tooltip>
      <Popover open={Boolean(anchor)} anchorEl={anchor} onClose={() => setAnchor(null)} anchorOrigin={{ vertical: "bottom", horizontal: "right" }} transformOrigin={{ vertical: "top", horizontal: "right" }}>
        <Box sx={{ width: { xs: "calc(100vw - 32px)", sm: 380 }, maxHeight: 520, overflowY: "auto", p: 2 }}>
          <Typography sx={{ fontWeight: 800, fontSize: 16, mb: 1.5 }}>{tr("shell.notifications")}</Typography>
          {groups.map((g) => {
            const meta = NOTIFICATION_MODULES[g.module] ?? NOTIFICATION_MODULES.general;
            return (
              <Box key={g.module} sx={{ mb: 2 }}>
                <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
                  <Emoji name={meta.icon} size={16} />
                  <Typography sx={{ fontWeight: 700, fontSize: 13, flex: 1 }}>{tr(meta.labelKey)}</Typography>
                  <Chip size="small" label={tr("shell.updates", { count: g.items.length })} />
                </Stack>
                <Stack spacing={0.75}>
                  {g.items.slice(0, 5).map((i) => (
                    <Box key={i.id} sx={{ p: "8px 10px", borderRadius: "10px", bgcolor: t.surface2, border: `1px solid ${t.line}` }}>
                      <Typography sx={{ fontSize: 13, fontWeight: 600 }}>{i.title}</Typography>
                      {i.created_at && <Typography variant="caption">{new Date(i.created_at).toLocaleString()}</Typography>}
                    </Box>
                  ))}
                </Stack>
              </Box>
            );
          })}
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1 }}>
            <Emoji name="briefcase" size={16} />
            <Typography sx={{ fontWeight: 700, fontSize: 13 }}>{tr("shell.hiring_activity")}</Typography>
          </Stack>
          <RecentActivityFeed limit={8} dense />
        </Box>
      </Popover>
    </>
  );
}

function ProfileMenu({ onLogout }: { onLogout: () => void }) {
  const t = useTheme().palette.fresh;
  const tr = useT();
  const { locale, setLocale } = useI18n();
  const { reload } = useMeBootstrap();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  if (!user) return null;
  // K-B2: the user's own language, saved as their preference so every device follows it.
  const chooseLanguage = (code: string) => {
    setAnchor(null);
    setLocale(code);
    experienceApi.updatePreferences({ locale: code }).then(reload).catch(() => undefined);
  };
  const name = user.full_name || user.email;
  return (
    <>
      <Tooltip title={tr("shell.profile")}>
        <IconButton onClick={(e) => setAnchor(e.currentTarget)} aria-label={tr("shell.profile_open")} aria-haspopup="menu" sx={{ p: 0.25 }}>
          <Avatar variant="rounded" sx={{ width: 38, height: 38, bgcolor: t.skySoft, color: t.sky, fontWeight: 800, fontSize: 14 }}>{initials(name)}</Avatar>
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)} anchorOrigin={{ vertical: "bottom", horizontal: "right" }} transformOrigin={{ vertical: "top", horizontal: "right" }}>
        <Box sx={{ px: 2, py: 1.25, minWidth: 220 }}>
          <Typography sx={{ fontWeight: 700 }} noWrap>{name}</Typography>
          <Typography variant="caption" component="div" noWrap>{user.email}</Typography>
          <Chip size="small" color="primary" label={user.role} sx={{ mt: 0.75, textTransform: "capitalize" }} />
        </Box>
        <Divider sx={{ my: 0.5 }} />
        <Stack direction="row" alignItems="center" spacing={1} sx={{ px: 2, pt: 0.5, pb: 0.25, color: t.muted }}>
          <TranslateOutlinedIcon sx={{ fontSize: 16 }} />
          <Typography variant="caption" sx={{ fontWeight: 700 }}>{tr("shell.language")}</Typography>
        </Stack>
        {LOCALES.map((l) => (
          <MenuItem key={l.code} selected={locale === l.code} onClick={() => chooseLanguage(l.code)} lang={l.code}>
            <ListItemIcon>{locale === l.code && <CheckIcon fontSize="small" />}</ListItemIcon>{l.label}
          </MenuItem>
        ))}
        <Divider sx={{ my: 0.5 }} />
        <MenuItem onClick={() => { setAnchor(null); navigate("/settings"); }}>
          <ListItemIcon><SettingsOutlinedIcon fontSize="small" /></ListItemIcon>{tr("shell.settings")}
        </MenuItem>
        <MenuItem onClick={() => { setAnchor(null); onLogout(); }}>
          <ListItemIcon><LogoutOutlinedIcon fontSize="small" /></ListItemIcon>{tr("shell.logout")}
        </MenuItem>
      </Menu>
    </>
  );
}

export default function AppLayout() {
  const theme = useTheme();
  const t = theme.palette.fresh;
  const tr = useT();
  const { locale } = useI18n();
  const isDesktop = useMediaQuery(theme.breakpoints.up("md"));
  const { logout } = useAuth();
  const { mode, toggleMode } = useThemeMode();
  const navigate = useNavigate();
  const items = useShellNav();
  const [confirmLogoutOpen, setConfirmLogoutOpen] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [expanded, setExpanded] = useState(() => readStorage(SIDEBAR_STORAGE_KEY) !== "false");

  useEffect(() => writeStorage(SIDEBAR_STORAGE_KEY, String(expanded)), [expanded]);

  const searchPages = useMemo(
    () => items.flatMap((i) => [{ label: i.label, path: i.path }, ...(i.children ?? []).map((c) => ({ label: `${i.label} — ${c.label}`, path: c.path }))]),
    [items],
  );

  const handleLogout = () => {
    setConfirmLogoutOpen(false);
    logout();
    navigate("/login", { replace: true });
  };

  const sidebarWidth = expanded ? SIDEBAR_WIDTH : RAIL_WIDTH;

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: t.ground, px: { xs: 1.5, sm: 2, xl: 3 } }}>
      {/* WCAG 2.4.1 bypass block: first focusable element on every page. */}
      <Box component="a" href="#main-content" sx={{ position: "absolute", left: -9999, top: 8, zIndex: 2000, p: 1, bgcolor: "background.paper", borderRadius: 1, "&:focus": { left: 8 } }}>
        {tr("shell.skip_to_content")}
      </Box>
      <Box
        sx={{
          // 16.1: no centred max-width -- sidebar on the left, content fills every remaining pixel.
          width: "100%", pt: 2, pb: 5, display: "grid", gap: { xs: 2, lg: 2.5 }, alignItems: "start",
          gridTemplateColumns: { xs: "minmax(0,1fr)", md: `${sidebarWidth}px minmax(0,1fr)` },
          transition: "grid-template-columns 220ms ease",
        }}
      >
        {isDesktop ? (
          <Box sx={{ position: "sticky", top: 16, height: "calc(100vh - 32px)" }}>
            <Sidebar items={items} expanded={expanded} onToggle={() => setExpanded((e) => !e)} />
          </Box>
        ) : (
          <Drawer open={mobileOpen} onClose={() => setMobileOpen(false)} slotProps={{ paper: { sx: { width: 280, bgcolor: "transparent", boxShadow: "none", p: 1.5 } } }}>
            <Sidebar items={items} expanded onNavigate={() => setMobileOpen(false)} />
          </Drawer>
        )}

        <Box sx={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 2.25 }}>
          <Box component="header" sx={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 1.5 }}>
            {!isDesktop && (
              <IconButton onClick={() => setMobileOpen(true)} aria-label={tr("shell.menu_open")} sx={{ bgcolor: t.surface, border: `1px solid ${t.line}` }}>
                <MenuIcon fontSize="small" />
              </IconButton>
            )}
            {/* L-N3: Ctrl/Cmd+K global search (server-side, permission-scoped). */}
            <GlobalSearch pages={searchPages} />
            <Stack direction="row" spacing={1} alignItems="center" sx={{ ml: "auto" }}>
              <ModuleTour />
              <Tooltip title={mode === "dark" ? tr("shell.theme_light") : tr("shell.theme_dark")}>
                <IconButton onClick={toggleMode} aria-label={mode === "dark" ? tr("shell.theme_light") : tr("shell.theme_dark")} sx={{ bgcolor: t.surface, border: `1px solid ${t.line}` }}>
                  {mode === "dark" ? <LightModeOutlinedIcon fontSize="small" /> : <DarkModeOutlinedIcon fontSize="small" />}
                </IconButton>
              </Tooltip>
              <NotificationsBell />
              <ProfileMenu onLogout={() => setConfirmLogoutOpen(true)} />
            </Stack>
          </Box>
          <Box component="main" id="main-content" tabIndex={-1} sx={{ minWidth: 0, outline: "none" }}>
            {/* Remount the page on a language change so every label (hook or plain t()) re-renders. */}
            <Outlet key={locale} />
          </Box>
        </Box>
      </Box>
      <CopilotWidget />

      <ConfirmDialog
        open={confirmLogoutOpen}
        title={tr("shell.logout_title")}
        message={tr("shell.logout_message")}
        confirmLabel={tr("shell.logout")}
        destructive={false}
        onConfirm={handleLogout}
        onCancel={() => setConfirmLogoutOpen(false)}
      />
    </Box>
  );
}
