import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import SearchIcon from "@mui/icons-material/Search";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import InputAdornment from "@mui/material/InputAdornment";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";

import { integrationsApi } from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ROLE_MATRIX } from "../auth/roles";
import HrMailboxSettingsCard from "../components/HrMailboxSettingsCard";
import InterviewTrackerSettingsCard from "../components/InterviewTrackerSettingsCard";
import PlatformSettingsPanel from "../components/PlatformSettingsPanel";
import ConnectionsPanel from "../components/ConnectionsPanel";
import CommunicationsPanel from "../components/CommunicationsPanel";
import AccessControlPanel from "../components/AccessControlPanel";
import WorkflowsPanel from "../components/WorkflowsPanel";
import MetadataPanel from "../components/MetadataPanel";
import CoreHrPanel from "../components/CoreHrPanel";
import RecruitmentPanel from "../components/RecruitmentPanel";
import OnboardingPanel from "../components/OnboardingPanel";
import PerformancePanel from "../components/PerformancePanel";
import ServiceDeskPanel from "../components/ServiceDeskPanel";
import PrivacyPanel from "../components/PrivacyPanel";
import MfaSettingsCard from "../components/MfaSettingsCard";
import MediaSettingsPanel from "../components/MediaSettingsPanel";
import BrandingGuideCard from "../components/settings/BrandingGuideCard";
import IntegrationCard from "../components/settings/IntegrationCard";
import SettingsTree, { type TreeGroup } from "../components/settings/SettingsTree";
import { useT } from "../i18n";
import { EmptyState, Emoji, PageHeader } from "../ui-kit";

type GroupId = "you" | "company" | "rules" | "modules" | "everything";

interface Category {
  id: string;
  group: GroupId;
  emoji: string;
  /** Older links (error "fix" buttons, setup checklist) that should land here. */
  aliases?: string[];
  visible: boolean;
  content: ReactNode;
}

const GROUP_ORDER: GroupId[] = ["you", "company", "rules", "modules", "everything"];

function normalise(text: string): string {
  return text.toLocaleLowerCase().normalize("NFKD").replace(/\p{M}/gu, "");
}

export default function SettingsPage() {
  const { can } = useAuth();
  const canManageHrIntegration = can(ROLE_MATRIX.hrIntegrationWrite);
  const canManagePlatformSettings = can(ROLE_MATRIX.platformSettingsWrite);
  const t = useT();
  const f = useTheme().palette.fresh;
  const location = useLocation();
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const contentRef = useRef<HTMLDivElement>(null);

  const open = (id: string) => {
    navigate({ hash: id }, { replace: false });
  };

  // Every existing panel, each behind exactly the permission check it had before.
  const categories: Category[] = useMemo(
    () => [
      {
        id: "account", group: "you", emoji: "key", aliases: ["security", "mfa", "calendar", "my-account"], visible: true,
        content: (
          <>
            <MfaSettingsCard />
            <IntegrationCard
              emoji="calendar"
              title={t("settingsPage.integration.google.title")}
              description={t("settingsPage.integration.google.body")}
              connectLabel={t("settingsPage.integration.google.connect")}
              fetchStatus={integrationsApi.googleStatus}
              connect={integrationsApi.connectGoogle}
            />
            <IntegrationCard
              emoji="writing_hand"
              title={t("settingsPage.integration.docusign.title")}
              description={t("settingsPage.integration.docusign.body")}
              connectLabel={t("settingsPage.integration.docusign.connect")}
              fetchStatus={integrationsApi.docusignStatus}
              connect={integrationsApi.connectDocusign}
            />
            <IntegrationCard
              emoji="handshake"
              title={t("settingsPage.integration.linkedin.title")}
              description={t("settingsPage.integration.linkedin.body")}
              connectLabel={t("settingsPage.integration.linkedin.connect")}
              fetchStatus={integrationsApi.linkedinStatus}
              connect={integrationsApi.connectLinkedin}
            />
          </>
        ),
      },
      { id: "branding", group: "company", emoji: "sparkles", aliases: ["company"], visible: canManagePlatformSettings, content: <BrandingGuideCard onOpen={open} /> },
      {
        id: "connections", group: "company", emoji: "link", aliases: ["ai", "copilot", "mailbox", "mailboxes"], visible: canManageHrIntegration || canManagePlatformSettings,
        content: (
          <>
            {canManageHrIntegration && <HrMailboxSettingsCard />}
            {canManagePlatformSettings && <ConnectionsPanel />}
          </>
        ),
      },
      { id: "communications", group: "company", emoji: "mail", aliases: ["emails", "notifications"], visible: canManagePlatformSettings, content: <CommunicationsPanel /> },
      { id: "media", group: "company", emoji: "clapper", aliases: ["settings-media", "tours", "video"], visible: canManagePlatformSettings, content: <MediaSettingsPanel /> },
      { id: "privacy", group: "company", emoji: "lock", aliases: ["dpdp"], visible: canManagePlatformSettings, content: <PrivacyPanel /> },
      { id: "workflows", group: "rules", emoji: "check", aliases: ["approvals"], visible: canManagePlatformSettings, content: <WorkflowsPanel /> },
      { id: "metadata", group: "rules", emoji: "label", aliases: ["custom-fields", "fields"], visible: canManagePlatformSettings, content: <MetadataPanel /> },
      { id: "access", group: "rules", emoji: "shield", aliases: ["roles"], visible: canManagePlatformSettings, content: <AccessControlPanel /> },
      {
        id: "hiring", group: "modules", emoji: "briefcase", aliases: ["recruitment", "interviews"], visible: true,
        content: (
          <>
            <InterviewTrackerSettingsCard />
            {canManagePlatformSettings && <RecruitmentPanel />}
          </>
        ),
      },
      { id: "onboarding", group: "modules", emoji: "waving_hand", visible: canManagePlatformSettings, content: <OnboardingPanel /> },
      { id: "core-hr", group: "modules", emoji: "people", aliases: ["people", "employees"], visible: canManagePlatformSettings, content: <CoreHrPanel /> },
      { id: "performance", group: "modules", emoji: "target", visible: canManagePlatformSettings, content: <PerformancePanel /> },
      { id: "helpdesk", group: "modules", emoji: "ring_buoy", aliases: ["assets", "exits", "service-desk"], visible: canManagePlatformSettings, content: <ServiceDeskPanel /> },
      { id: "all", group: "everything", emoji: "gear", aliases: ["modules", "platform", "all-settings"], visible: canManagePlatformSettings, content: <PlatformSettingsPanel /> },
    ],
    // `open` only calls navigate; t changes with the language.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [canManageHrIntegration, canManagePlatformSettings, t],
  );

  const visible = categories.filter((c) => c.visible);
  const title = (c: Category) => t(`settingsPage.cat.${c.id}.title`);
  const hint = (c: Category) => t(`settingsPage.cat.${c.id}.hint`);
  const keywords = (c: Category) => t(`settingsPage.cat.${c.id}.keywords`);

  // #<category> deep links, including the older names error "fix" buttons still use.
  const hash = decodeURIComponent(location.hash.replace(/^#/, "")).toLowerCase();
  const fromHash = visible.find((c) => c.id === hash || c.aliases?.includes(hash));
  const selected = fromHash ?? visible[0];

  useEffect(() => {
    if (hash && fromHash) contentRef.current?.scrollIntoView?.({ block: "start" });
  }, [hash, fromHash]);

  const q = normalise(query.trim());
  const matches = q
    ? visible.filter((c) => normalise(`${title(c)} ${hint(c)} ${keywords(c)} ${c.id} ${(c.aliases ?? []).join(" ")}`).includes(q))
    : visible;

  // While searching, show the first match if the open category is filtered out.
  const shown = q && selected && !matches.includes(selected) ? matches[0] : selected;

  const groups: TreeGroup[] = GROUP_ORDER.map((g) => ({
    id: g,
    label: t(`settingsPage.group.${g}`),
    items: matches.filter((c) => c.group === g).map((c) => ({ id: c.id, label: title(c), emoji: c.emoji })),
  })).filter((g) => g.items.length > 0);

  const search = (
    <TextField
      value={query}
      onChange={(e) => setQuery(e.target.value)}
      placeholder={t("settingsPage.search_placeholder")}
      size="small"
      fullWidth
      slotProps={{
        htmlInput: { "aria-label": t("settingsPage.search_label") },
        input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> },
      }}
      sx={{ maxWidth: 460 }}
    />
  );

  return (
    <Box>
      <PageHeader emoji="gear" title={t("settingsPage.title")} purpose={t("settingsPage.purpose")} tourKey="settings" below={search} />

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "260px minmax(0, 1fr)" }, gap: 2.5, alignItems: "start" }}>
        <Card component="nav" aria-label={t("settingsPage.tree_label")} sx={{ p: 1.5, position: { md: "sticky" }, top: { md: 16 }, maxHeight: { md: "calc(100vh - 32px)" }, overflowY: "auto" }}>
          {groups.length === 0 ? (
            <Typography sx={{ color: f.muted, p: 1.5, fontSize: 13 }}>{t("settingsPage.search_none_short")}</Typography>
          ) : (
            <SettingsTree groups={groups} selected={shown?.id ?? ""} onSelect={open} label={t("settingsPage.tree_label")} forceExpanded={Boolean(q)} />
          )}
        </Card>

        <Box ref={contentRef} sx={{ minWidth: 0, scrollMarginTop: 16 }}>
          {q && matches.length === 0 ? (
            <Card>
              <EmptyState
                illustration="search"
                title={t("settingsPage.search_none", { query: query.trim() })}
                hint={t("settingsPage.search_none_hint")}
                action={<Button variant="contained" onClick={() => setQuery("")}>{t("settingsPage.search_clear")}</Button>}
              />
            </Card>
          ) : shown ? (
            <Box role="region" aria-labelledby="settings-category-title" id={shown.id}>
              <Stack direction="row" spacing={1.5} alignItems="center" sx={{ mb: 2 }}>
                <Box sx={{ width: 40, height: 40, borderRadius: "12px", bgcolor: f.brandSoft, display: "grid", placeItems: "center", flexShrink: 0 }}>
                  <Emoji name={shown.emoji} size={22} />
                </Box>
                <Box sx={{ minWidth: 0 }}>
                  <Typography id="settings-category-title" component="h2" sx={{ fontWeight: 800, fontSize: 20 }}>{title(shown)}</Typography>
                  <Typography sx={{ color: f.muted }}>{hint(shown)}</Typography>
                </Box>
              </Stack>
              <Stack spacing={3} key={shown.id}>{shown.content}</Stack>
            </Box>
          ) : null}
        </Box>
      </Box>
    </Box>
  );
}
