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
import ModulePicker from "../components/modules/ModulePicker";
import ModulesOnOffCard from "../components/modules/ModulesOnOffCard";
import JobBoardsPage from "../components/jobboards/JobBoardsPage";
import BudgetsSettingsPage from "../components/salary/BudgetsSettingsPage";
import RequiredDocumentsPage from "../components/documents/RequiredDocumentsPage";
import ContactsSettingsPage from "../components/offers/ContactsSettingsPage";
import OfficesPage from "../components/people/OfficesPage";
import PoliciesPage from "../components/policies/PoliciesPage";
import CategoryListPage from "../components/servicedesk/CategoryListPage";
import JoiningFormSettingsPage from "../components/onboarding/JoiningFormSettingsPage";
import EmployeeIdSettings from "../components/employees/EmployeeIdSettings";
import ExitInterviewSettingsPage from "../components/exits/ExitInterviewSettings";
import ExitChecklistSettingsPage from "../components/exits/ExitChecklistSettings";
import UsersPage from "../components/people/UsersPage";
import GenAISettingsPage from "../components/genai/GenAISettingsPage";
import PrivacyPanel from "../components/PrivacyPanel";
import RecruitmentPanel from "../components/RecruitmentPanel";
import ServiceDeskPanel from "../components/ServiceDeskPanel";
import WorkflowsPanel from "../components/WorkflowsPanel";
import ScoringRulesEditor from "../components/scoring/ScoringRulesEditor";
import ShortlistingRulesForm from "../components/scoring/ShortlistingRulesForm";
import BrandingGuideCard from "../components/settings/BrandingGuideCard";
import IntegrationCard from "../components/settings/IntegrationCard";
import SystemHealthPage from "../components/settings/SystemHealthPage";
import IgnoredChecksCard from "../components/settings/IgnoredChecksCard";
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
  /** Part 19.1: hidden when this "Choose what you use" module isn't active */
  module?: string;
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
  modules?: string[]; // Part 19.1: modules active for the company (bootstrap.company_modules.active)
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
  hiring: "hiring/stages", recruitment: "hiring/stages", requests: "hiring/stages", "hiring/requests": "hiring/stages", requisitions: "hiring/stages", scoring: "hiring/scoring", "scoring-rules": "hiring/scoring", shortlisting: "hiring/scoring", interviews: "hiring/interviews", onboarding: "onboarding/plans",
  "core-hr": "onboarding/org", people: "onboarding/org", employees: "onboarding/org", performance: "performance/cycles",
  helpdesk: "helpdesk/main", assets: "helpdesk/main", exits: "helpdesk/main", "service-desk": "helpdesk/main",
  all: "advanced/all", modules: "company/modules", "module-lock": "company/modules", "advanced/modules": "company/modules", platform: "advanced/all", "all-settings": "advanced/all",
  health: "data/health", "system-health": "data/health",
  "employee-id": "onboarding/employee-id", "exit-interview": "onboarding/exit-interview",
  "joining-form": "onboarding/joining-form", "joining-details": "onboarding/joining-form",
  "asset-types": "helpdesk/asset-types", "asset-categories": "helpdesk/asset-types", "exit-reasons": "helpdesk/exit-reasons",
  policies: "company/policies", handbook: "company/policies", knowledge: "company/policies",
};

export const CATEGORIES: SettingsCategory[] = [
  {
    id: "company", emoji: "building", pages: [
      { id: "profile", emoji: "building", prefixes: ["org."], visible: ADMIN, render: scoped(["org."], "settingsHome.page.company.profile") },
      { id: "branding", emoji: "sparkles", keywords: "logo colours colors theme email design", visible: ADMIN,
        render: (go) => (<><BrandingGuideCard onOpen={(id) => go(LEGACY[id] ?? "advanced/all")} /><CommunicationsPanel only="brand" /></>) },
      // Part 18.22: real offices (add / edit / delete / map); departments & positions stay underneath
      { id: "offices", emoji: "pin", keywords: "locations offices map address departments", visible: ADMIN,
        render: () => (<><OfficesPage /><CoreHrPanel only="Org" /></>) },
      { id: "languages", emoji: "globe", keywords: "hindi tamil rename labels translation", visible: ADMIN, render: () => <LanguagesPage /> },
      { id: "media", emoji: "clapper", keywords: "welcome video tours show me how gif", visible: ADMIN, render: () => <MediaSettingsPanel /> },
      // fix 2026-10-05: what the HR assistant answers from -- here, not under Helpdesk, so it works when Helpdesk is off
      { id: "policies", emoji: "page", keywords: "policies handbook policy documents hr assistant copilot knowledge upload leave conduct benefits", visible: ADMIN,
        render: () => <PoliciesPage /> },
      // Part 19.1: "Choose what you use" + activation code; the other (non-hiring) modules underneath
      { id: "modules", emoji: "puzzle", keywords: "modules choose what you use activation code activate switch on off", visible: ADMIN,
        render: () => (<><ModulePicker /><ModulesOnOffCard /></>) },
    ],
  },
  {
    id: "people", emoji: "people", pages: [
      { id: "users", emoji: "id_card", keywords: "user access assign role invite deactivate password reset", visible: ADMIN,
        render: () => (<><UsersPage /><AccessControlPanel only="Assignments" /></>) },
      { id: "roles", emoji: "shield", keywords: "permissions rights", visible: ADMIN, render: () => <AccessControlPanel only="Roles" /> },
      { id: "two-step", emoji: "lock", keywords: "2fa mfa otp authenticator security", prefixes: ["iam.auth.mfa"], visible: (p) => Boolean(p.twoStep), render: () => <TwoStepPage /> },
      { id: "signin", emoji: "key", keywords: "password lockout session login", prefixes: ["iam.auth."], visible: ADMIN, render: scoped(["iam.auth."], "settingsHome.page.people.signin") },
      { id: "review", emoji: "eyes", advanced: true, keywords: "access review audit", visible: ADMIN, render: () => <AccessControlPanel only="Access review" /> },
    ],
  },
  {
    id: "hiring", emoji: "briefcase", pages: [
      // Part 18.22: "Hiring stages" and "Job requests" are one page with two tabs (they showed the same thing)
      { id: "stages", emoji: "briefcase", module: "jobs", keywords: "pipeline hiring stages job requests requisitions approval", visible: ADMIN,
        render: () => <RecruitmentPanel tabs={["Pipeline", "Requisitions"]} /> },
      // Part 17.5/17.6: the Match score's rules + automatic shortlisting (their raw settings live here too).
      { id: "scoring", emoji: "target", module: "screening", keywords: "score weight match threshold knockout shortlist auto-shortlist preset", visible: ADMIN,
        prefixes: ["recruitment.scoring.", "recruitment.shortlisting."],
        render: () => (<><ScoringRulesEditor /><ShortlistingRulesForm /></>) },
      { id: "screening", emoji: "magnifier", module: "screening", keywords: "ai negotiation tracker blind", prefixes: ["recruitment."], visible: ADMIN,
        render: scoped(["recruitment."], "settingsHome.page.hiring.screening") },
      { id: "interviews", emoji: "calendar", module: "interviews", keywords: "interview scheduling availability interviewer pools negotiation slots", prefixes: ["recruitment.negotiation.", "recruitment.interviews."], visible: EVERYONE, render: () => (<><InterviewsSettingsPage />{scoped(["recruitment.interviews."], "settingsHome.page.hiring.interviews_auto")()}</>) },
      { id: "availability", emoji: "hourglass", module: "interviews", keywords: "interviewer availability ctc salary components", visible: ADMIN,
        render: () => <RecruitmentPanel only="Availability & CTC" /> },
      { id: "offers", emoji: "envelope", module: "offers", keywords: "salary bands ctc offer expiry", prefixes: ["compensation.", "offers."], visible: ADMIN,
        render: scoped(["compensation.", "offers."], "settingsHome.page.hiring.offers") },
      { id: "bgv", emoji: "shield", module: "bgv", keywords: "background checks verification vendor", prefixes: ["onboarding.bgv."], visible: ADMIN,
        render: scoped(["onboarding.bgv."], "settingsHome.page.hiring.bgv") },
      { id: "documents", emoji: "file_folder", module: "bgv", keywords: "required documents joining pan aadhaar payslip certificate upload", visible: ADMIN, render: () => <RequiredDocumentsPage /> },
      { id: "contacts", emoji: "id_card", module: "offers", keywords: "contacts welcome email hr department head management joining", visible: ADMIN, render: () => <ContactsSettingsPage /> },
      { id: "budgets", emoji: "bank", module: "salary", keywords: "department budget finance hiring cost money fiscal year", visible: ADMIN, render: () => <BudgetsSettingsPage /> },
      { id: "careers", emoji: "globe", module: "jobs", keywords: "careers site benefits faq", prefixes: ["careers."], visible: ADMIN, render: scoped(["careers."], "settingsHome.page.hiring.careers") },
      { id: "boards", emoji: "link", module: "jobs", keywords: "linkedin naukri indeed job boards posting", visible: EVERYONE,
        render: () => (
          <IntegrationCard emoji="handshake" title={t("settingsPage.integration.linkedin.title")} description={t("settingsPage.integration.linkedin.body")}
            connectLabel={t("settingsPage.integration.linkedin.connect")} fetchStatus={integrationsApi.linkedinStatus} connect={integrationsApi.connectLinkedin} />
        ) },
    ],
  },
  {
    id: "onboarding", emoji: "waving_hand", pages: [
      { id: "plans", emoji: "clipboard", module: "onboarding", keywords: "onboarding checklist tasks", visible: ADMIN, render: () => <OnboardingPanel /> },
      // Part 20.1: Employee ID format (prefix + running number + padding)
      { id: "employee-id", emoji: "id_card", keywords: "employee id number code format prefix padding", visible: ADMIN, render: () => <EmployeeIdSettings /> },
      // change 2026-10-05: required / optional / hidden for every joining-details field and joining document
      { id: "joining-form", emoji: "memo", module: "onboarding", keywords: "joining details form fields required optional hidden pan aadhaar bank ifsc help text format check documents",
        prefixes: ["onboarding.joining_form"], visible: ADMIN, render: () => <JoiningFormSettingsPage /> },
      { id: "documents", emoji: "page", module: "onboarding", keywords: "documents letters portal forms policies", prefixes: ["onboarding.", "core_hr."], visible: ADMIN,
        render: scoped(["onboarding.documents", "onboarding.portal", "onboarding.conversion", "core_hr."], "settingsHome.page.onboarding.documents") },
      // fix 2026-10-06: the exit interview questions the leaving employee answers
      { id: "exit-interview", emoji: "speech", keywords: "exit interview questions leaving resignation feedback stars ai summary reminder", prefixes: ["employees.exit_interview"],
        visible: ADMIN, render: () => <ExitInterviewSettingsPage /> },
      // feat 2026-10-06: actionable exit checklist -- items, owners, due days, required, how each completes
      { id: "exit-checklist", emoji: "clipboard", keywords: "exit checklist clearance assets return id card access revoke finance settlement handover letters owners due",
        prefixes: ["employees.exit.clearance_items"], visible: ADMIN, render: () => <ExitChecklistSettingsPage /> },
      { id: "leavers", emoji: "door", module: "onboarding", keywords: "absconding not reporting no show early leaver notices", prefixes: ["onboarding.not_reporting"], visible: ADMIN,
        render: scoped(["onboarding.not_reporting"], "settingsHome.page.onboarding.leavers") },
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
      // Part 20.0-D: the lists behind the asset-type / exit-reason dropdowns (they were never seeded -> empty dropdowns)
      { id: "asset-types", emoji: "laptop", keywords: "asset categories types laptop monitor phone sim id card", visible: ADMIN, render: () => <CategoryListPage kind="asset" /> },
      { id: "exit-reasons", emoji: "door", keywords: "exit reasons resignation leaving", visible: ADMIN, render: () => <CategoryListPage kind="exit_reason" /> },
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
      // Part 18.23: GenAI settings -- provider, key, models, features, prices, limits (+ the older AI/copilot settings below)
      { id: "ai", emoji: "robot", keywords: "ai genai claude model provider api key assistant copilot limits tokens usage", prefixes: ["ai.", "copilot."], visible: ADMIN,
        render: () => (<><GenAISettingsPage />{scoped(["copilot."], "settingsHome.page.integrations.ai")()}</>) },
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
      { id: "job-boards", emoji: "globe", module: "jobs", keywords: "linkedin naukri indeed monster shine job boards import", visible: ADMIN, render: () => <JobBoardsPage /> },
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
      { id: "health", emoji: "check", keywords: "health status database mailbox ai storage jobs", visible: ADMIN, render: () => (<><SystemHealthPage /><IgnoredChecksCard /></>) },
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
    ],
  },
];

export function visibleCategories(p: Perms): SettingsCategory[] {
  const moduleOn = (pg: SettingsPageDef) => !pg.module || !p.modules || p.modules.includes(pg.module);
  return CATEGORIES.map((c) => ({ ...c, pages: c.pages.filter((pg) => pg.visible(p) && moduleOn(pg)) })).filter((c) => c.pages.length > 0);
}

/** The page that owns a raw setting key (longest matching prefix), else Advanced. */
export function pageForSetting(key: string, cats: SettingsCategory[]): string {
  let best: { path: string; len: number } | null = null;
  for (const c of cats) for (const pg of c.pages) for (const pre of pg.prefixes ?? []) {
    if (key.startsWith(pre) && (!best || pre.length > best.len)) best = { path: `${c.id}/${pg.id}`, len: pre.length };
  }
  return best?.path ?? "advanced/all";
}
