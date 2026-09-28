import type { ReactNode } from "react";

import { integrationsApi } from "../api/client";
import AccessControlPanel from "../components/AccessControlPanel";
import CommunicationsPanel from "../components/CommunicationsPanel";
import ConnectionsPanel from "../components/ConnectionsPanel";
import CoreHrPanel from "../components/CoreHrPanel";
import HrMailboxSettingsCard from "../components/HrMailboxSettingsCard";
import MediaSettingsPanel from "../components/MediaSettingsPanel";
import MetadataPanel from "../components/MetadataPanel";
import OnboardingPanel from "../components/OnboardingPanel";
import PerformancePanel from "../components/PerformancePanel";
import PlatformSettingsPanel from "../components/PlatformSettingsPanel";
import ModuleLockSettingsPage from "../components/modules/ModuleLockSettingsPage";
import JobBoardsPage from "../components/jobboards/JobBoardsPage";
import PrivacyPanel from "../components/PrivacyPanel";
import RecruitmentPanel from "../components/RecruitmentPanel";
import ServiceDeskPanel from "../components/ServiceDeskPanel";
import WorkflowsPanel from "../components/WorkflowsPanel";
import ScoringRulesEditor from "../components/scoring/ScoringRulesEditor";
import ShortlistingRulesForm from "../components/scoring/ShortlistingRulesForm";
import BrandingGuideCard from "../components/settings/BrandingGuideCard";
import IntegrationCard from "../components/settings/IntegrationCard";
import SystemHealthPage from "../components/settings/SystemHealthPage";
import { t } from "../i18n";
import { AuditLogPage, BillingPage, ImportsPage, InterviewsSettingsPage, LanguagesPage, SamplesPage, StoragePage, TwoStepPage } from "./pages";

// Part 16.3: Settings = short, grouped, searchable. Nothing was removed -- every earlier panel
// is a page here, behind the same permission it had. Rarely used pages are `advanced` (shown
// under "Advanced" inside their category). `prefixes` = the raw settings this page owns, so the
// home search can send a setting to the right page.

export interface SettingsPageDef {
  id: string;
  emoji: string;
  advanced?: boolean;
  prefixes?: string[];
  /** extra words people might search for */
  keywords?: string;
  visible: (p: Perms) => boolean;
  render: (go: (path: string) => void) => ReactNode;
}

export interface SettingsCategory {
  id: string;
  emoji: string;
  pages: SettingsPageDef[];
}

export interface Perms {
  admin: boolean; // platform settings configure
  mailbox: boolean; // HR mailbox integration
  twoStep?: boolean; // Part 18.1: 2-step verification switched on (Settings > Advanced)
}

const ADMIN = (p: Perms) => p.admin;
const EVERYONE = () => true;

const scoped = (prefixes: string[], titleKey: string) => () => (
  <PlatformSettingsPanel prefixes={prefixes} title={t(titleKey)} intro={t("settingsHome.scoped_intro")} />
);

export const LEGACY: Record<string, string> = {
  account: "people/two-step", security: "people/two-step", mfa: "people/two-step", "my-account": "people/two-step", calendar: "integrations/calendars",
  branding: "company/branding", company: "company/profile", media: "company/media", "settings-media": "company/media", tours: "company/media", video: "company/media",
  connections: "integrations/connections", ai: "integrations/ai", copilot: "integrations/ai", mailbox: "communication/mailboxes", mailboxes: "communication/mailboxes",
  communications: "communication/templates", emails: "communication/templates", notifications: "communication/rules",
  privacy: "data/privacy", dpdp: "data/privacy", workflows: "automation/approvals", approvals: "automation/approvals",
  metadata: "data/fields", "custom-fields": "data/fields", fields: "data/fields", access: "people/roles", roles: "people/roles",
  hiring: "hiring/stages", recruitment: "hiring/stages", scoring: "hiring/scoring", "scoring-rules": "hiring/scoring", shortlisting: "hiring/scoring", interviews: "hiring/interviews", onboarding: "onboarding/plans",
  "core-hr": "onboarding/org", people: "onboarding/org", employees: "onboarding/org", performance: "performance/cycles",
  helpdesk: "helpdesk/main", assets: "helpdesk/main", exits: "helpdesk/main", "service-desk": "helpdesk/main",
  all: "advanced/all", modules: "advanced/modules", "module-lock": "advanced/modules", platform: "advanced/all", "all-settings": "advanced/all",
  health: "data/health", "system-health": "data/health",
};

export const CATEGORIES: SettingsCategory[] = [
  {
    id: "company", emoji: "building", pages: [
      { id: "profile", emoji: "building", prefixes: ["org."], visible: ADMIN, render: scoped(["org."], "settingsHome.page.company.profile") },
      { id: "branding", emoji: "sparkles", keywords: "logo colours colors theme email design", visible: ADMIN,
        render: (go) => (<><BrandingGuideCard onOpen={(id) => go(LEGACY[id] ?? "advanced/all")} /><CommunicationsPanel only="brand" /></>) },
      { id: "offices", emoji: "pin", keywords: "locations departments", visible: ADMIN, render: () => <CoreHrPanel only="Org" /> },
      { id: "languages", emoji: "globe", keywords: "hindi tamil rename labels translation", visible: ADMIN, render: () => <LanguagesPage /> },
      { id: "media", emoji: "clapper", keywords: "welcome video tours show me how gif", visible: ADMIN, render: () => <MediaSettingsPanel /> },
    ],
  },
  {
    id: "people", emoji: "people", pages: [
      { id: "users", emoji: "id_card", keywords: "user access assign role", visible: ADMIN, render: () => <AccessControlPanel only="Assignments" /> },
      { id: "roles", emoji: "shield", keywords: "permissions rights", visible: ADMIN, render: () => <AccessControlPanel only="Roles" /> },
      { id: "two-step", emoji: "lock", keywords: "2fa mfa otp authenticator security", prefixes: ["iam.auth.mfa"], visible: (p) => Boolean(p.twoStep), render: () => <TwoStepPage /> },
      { id: "signin", emoji: "key", keywords: "password lockout session login", prefixes: ["iam.auth."], visible: ADMIN, render: scoped(["iam.auth."], "settingsHome.page.people.signin") },
      { id: "review", emoji: "eyes", advanced: true, keywords: "access review audit", visible: ADMIN, render: () => <AccessControlPanel only="Access review" /> },
    ],
  },
  {
    id: "hiring", emoji: "briefcase", pages: [
      { id: "stages", emoji: "briefcase", keywords: "pipeline hiring stages", visible: ADMIN, render: () => <RecruitmentPanel only="Pipeline" /> },
      { id: "requests", emoji: "clipboard", keywords: "job requests requisitions approval", visible: ADMIN, render: () => <RecruitmentPanel only="Requisitions" /> },
      // Part 17.5/17.6: the Match score's rules + automatic shortlisting (their raw settings live here too).
      { id: "scoring", emoji: "target", keywords: "score weight match threshold knockout shortlist auto-shortlist preset", visible: ADMIN,
        prefixes: ["recruitment.scoring.", "recruitment.shortlisting."],
        render: () => (<><ScoringRulesEditor /><ShortlistingRulesForm /></>) },
      { id: "screening", emoji: "magnifier", keywords: "ai negotiation tracker blind", prefixes: ["recruitment."], visible: ADMIN,
        render: scoped(["recruitment."], "settingsHome.page.hiring.screening") },
      { id: "interviews", emoji: "calendar", keywords: "interview scheduling availability interviewer pools negotiation slots", prefixes: ["recruitment.negotiation."], visible: EVERYONE, render: () => <InterviewsSettingsPage /> },
      { id: "availability", emoji: "hourglass", keywords: "interviewer availability ctc salary components", visible: ADMIN,
        render: () => <RecruitmentPanel only="Availability & CTC" /> },
      { id: "offers", emoji: "envelope", keywords: "salary bands ctc offer expiry", prefixes: ["compensation.", "offers."], visible: ADMIN,
        render: scoped(["compensation.", "offers."], "settingsHome.page.hiring.offers") },
      { id: "bgv", emoji: "shield", keywords: "background checks verification vendor", prefixes: ["onboarding.bgv."], visible: ADMIN,
        render: scoped(["onboarding.bgv."], "settingsHome.page.hiring.bgv") },
      { id: "careers", emoji: "globe", keywords: "careers site benefits faq", prefixes: ["careers."], visible: ADMIN, render: scoped(["careers."], "settingsHome.page.hiring.careers") },
      { id: "boards", emoji: "link", keywords: "linkedin naukri indeed job boards posting", visible: EVERYONE,
        render: () => (
          <IntegrationCard emoji="handshake" title={t("settingsPage.integration.linkedin.title")} description={t("settingsPage.integration.linkedin.body")}
            connectLabel={t("settingsPage.integration.linkedin.connect")} fetchStatus={integrationsApi.linkedinStatus} connect={integrationsApi.connectLinkedin} />
        ) },
    ],
  },
  {
    id: "onboarding", emoji: "waving_hand", pages: [
      { id: "plans", emoji: "clipboard", keywords: "onboarding checklist tasks", visible: ADMIN, render: () => <OnboardingPanel /> },
      { id: "documents", emoji: "page", keywords: "documents letters portal forms policies", prefixes: ["onboarding.", "core_hr."], visible: ADMIN,
        render: scoped(["onboarding.documents", "onboarding.portal", "onboarding.conversion", "core_hr."], "settingsHome.page.onboarding.documents") },
      { id: "fields", emoji: "label", keywords: "employee fields custom", visible: ADMIN, render: () => <MetadataPanel only="Custom Fields" /> },
      { id: "org", emoji: "building", keywords: "org structure departments positions", visible: ADMIN, render: () => <CoreHrPanel only="Org" /> },
      { id: "employees", emoji: "people", advanced: true, visible: ADMIN, render: () => <CoreHrPanel only="Employees" /> },
    ],
  },
  {
    id: "performance", emoji: "target", pages: [
      { id: "cycles", emoji: "target", keywords: "review cycles goals rating scales compensation planning", visible: ADMIN, render: () => <PerformancePanel /> },
      { id: "rules", emoji: "gear", prefixes: ["performance."], visible: ADMIN, render: scoped(["performance."], "settingsHome.page.performance.rules") },
    ],
  },
  {
    id: "helpdesk", emoji: "ring_buoy", pages: [
      { id: "main", emoji: "ring_buoy", keywords: "tickets categories response times assets exits", visible: ADMIN, render: () => <ServiceDeskPanel /> },
      { id: "rules", emoji: "gear", prefixes: ["helpdesk.", "assets.", "separation."], visible: ADMIN,
        render: scoped(["helpdesk.", "assets.", "separation."], "settingsHome.page.helpdesk.rules") },
    ],
  },
  {
    id: "communication", emoji: "mail", pages: [
      { id: "mailboxes", emoji: "inbox", keywords: "smtp imap gmail outlook mailbox", visible: (p) => p.mailbox || p.admin,
        render: () => <HrMailboxSettingsCard /> },
      { id: "templates", emoji: "mail", keywords: "email templates wording", visible: ADMIN, render: () => <CommunicationsPanel only="templates" /> },
      { id: "rules", emoji: "bell", keywords: "notification rules when emails are sent", visible: ADMIN, render: () => <CommunicationsPanel only="rules" /> },
      { id: "log", emoji: "memo", keywords: "message log sent emails resend", visible: ADMIN, render: () => <CommunicationsPanel only="log" /> },
      { id: "unsubscribed", emoji: "pause", advanced: true, visible: ADMIN, render: () => <CommunicationsPanel only="suppression" /> },
    ],
  },
  {
    id: "integrations", emoji: "link", pages: [
      { id: "connections", emoji: "link", keywords: "connections services accounts", visible: ADMIN, render: () => <ConnectionsPanel /> },
      { id: "ai", emoji: "robot", keywords: "ai claude model provider api key assistant copilot", prefixes: ["ai.", "copilot."], visible: ADMIN,
        render: scoped(["ai.", "copilot."], "settingsHome.page.integrations.ai") },
      { id: "esign", emoji: "writing_hand", keywords: "docusign leegality e-sign", visible: EVERYONE,
        render: () => (
          <IntegrationCard emoji="writing_hand" title={t("settingsPage.integration.docusign.title")} description={t("settingsPage.integration.docusign.body")}
            connectLabel={t("settingsPage.integration.docusign.connect")} fetchStatus={integrationsApi.docusignStatus} connect={integrationsApi.connectDocusign} />
        ) },
      { id: "calendars", emoji: "calendar", keywords: "google calendar teams zoom meet", visible: EVERYONE,
        render: () => (
          <IntegrationCard emoji="calendar" title={t("settingsPage.integration.google.title")} description={t("settingsPage.integration.google.body")}
            connectLabel={t("settingsPage.integration.google.connect")} fetchStatus={integrationsApi.googleStatus} connect={integrationsApi.connectGoogle} />
        ) },
      { id: "maps", emoji: "world_map", keywords: "maps geocoding tiles", prefixes: ["geo.", "maps."], visible: ADMIN, render: scoped(["geo.", "maps."], "settingsHome.page.integrations.maps") },
      { id: "storage", emoji: "file_folder", keywords: "file storage s3 space", visible: ADMIN, render: () => <StoragePage /> },
      { id: "job-boards", emoji: "globe", keywords: "linkedin naukri indeed monster shine job boards import", visible: ADMIN, render: () => <JobBoardsPage /> },
    ],
  },
  {
    id: "automation", emoji: "gear", pages: [
      { id: "approvals", emoji: "check", keywords: "approval steps workflows", visible: ADMIN, render: () => <WorkflowsPanel /> },
    ],
  },
  {
    id: "data", emoji: "lock", pages: [
      { id: "fields", emoji: "label", keywords: "custom fields", visible: ADMIN, render: () => <MetadataPanel only="Custom Fields" /> },
      { id: "lists", emoji: "clipboard", keywords: "drop-down lists masters reasons", visible: ADMIN, render: () => <MetadataPanel only="Masters" /> },
      { id: "numbering", emoji: "label", advanced: true, keywords: "numbering sequences codes", visible: ADMIN, render: () => <MetadataPanel only="Sequences" /> },
      { id: "imports", emoji: "package", keywords: "import export excel", visible: ADMIN, render: (go) => <ImportsPage go={go} /> },
      { id: "samples", emoji: "page", keywords: "sample files templates download", visible: ADMIN, render: () => <SamplesPage /> },
      { id: "privacy", emoji: "lock", keywords: "retention consent dpdp privacy requests", visible: ADMIN, render: () => <PrivacyPanel /> },
      { id: "audit", emoji: "eyes", keywords: "audit log history who changed", visible: ADMIN, render: () => <AuditLogPage /> },
      // Part 17.13: is everything the app depends on working? (the ui-kit has no stethoscope emoji)
      { id: "health", emoji: "check", keywords: "health status database mailbox ai storage jobs", visible: ADMIN, render: () => <SystemHealthPage /> },
    ],
  },
  {
    id: "billing", emoji: "money", pages: [
      { id: "usage", emoji: "money", keywords: "plan licence employees counted usage", visible: ADMIN, render: () => <BillingPage /> },
    ],
  },
  {
    id: "advanced", emoji: "tools", pages: [
      { id: "all", emoji: "tools", keywords: "all settings raw", visible: ADMIN, render: () => <PlatformSettingsPanel /> },
      { id: "modules", emoji: "lock", keywords: "modules lock unlock passcode", visible: ADMIN, render: () => <ModuleLockSettingsPage /> },
    ],
  },
];

export function visibleCategories(p: Perms): SettingsCategory[] {
  return CATEGORIES.map((c) => ({ ...c, pages: c.pages.filter((pg) => pg.visible(p)) })).filter((c) => c.pages.length > 0);
}

/** The page that owns a raw setting key (longest matching prefix), else Advanced. */
export function pageForSetting(key: string, cats: SettingsCategory[]): string {
  let best: { path: string; len: number } | null = null;
  for (const c of cats) for (const pg of c.pages) for (const pre of pg.prefixes ?? []) {
    if (key.startsWith(pre) && (!best || pre.length > best.len)) best = { path: `${c.id}/${pg.id}`, len: pre.length };
  }
  return best?.path ?? "advanced/all";
}
