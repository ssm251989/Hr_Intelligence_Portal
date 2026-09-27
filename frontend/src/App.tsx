import { lazy, Suspense } from "react";
import { Navigate, Route, BrowserRouter, Routes, useLocation } from "react-router-dom";
import CircularProgress from "@mui/material/CircularProgress";

import { AuthProvider } from "./auth/AuthContext";
import { BootstrapProvider } from "./bootstrap/BootstrapContext";
import { MeBootstrapProvider } from "./bootstrap/MeBootstrapContext";
import { AppThemeProvider } from "./theme/ThemeModeContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import { useAuth } from "./auth/AuthContext";
import ErrorBoundary from "./components/ErrorBoundary";
import AppLayout from "./layout/AppLayout";
import { I18nProvider } from "./i18n";

// Part 14 section 12: one bundle chunk per page (route-level code splitting).
const CareersApplyPage = lazy(() => import("./careers/CareersApplyPage"));
const CareersJobDetailPage = lazy(() => import("./careers/CareersJobDetailPage"));
const CareersLayout = lazy(() => import("./careers/CareersLayout"));
const CareersListPage = lazy(() => import("./careers/CareersListPage"));
const CareersThankYouPage = lazy(() => import("./careers/CareersThankYouPage"));
const BgvPage = lazy(() => import("./pages/BgvPage"));
const CandidateDetailPage = lazy(() => import("./pages/CandidateDetailPage"));
const CandidatesDashboardPage = lazy(() => import("./pages/CandidatesDashboardPage"));
const CandidatesImportPage = lazy(() => import("./pages/CandidatesImportPage"));
const CandidatesListPage = lazy(() => import("./pages/CandidatesListPage"));
const HrInboxListPage = lazy(() => import("./pages/HrInboxListPage"));
const InterviewListPage = lazy(() => import("./pages/InterviewListPage"));
const InterviewsDashboardPage = lazy(() => import("./pages/InterviewsDashboardPage"));
const JobsPage = lazy(() => import("./pages/JobsPage"));
const LoginPage = lazy(() => import("./pages/LoginPage"));
const OffersPage = lazy(() => import("./pages/OffersPage"));
const OverviewPage = lazy(() => import("./pages/OverviewPage"));
const HomePage = lazy(() => import("./pages/HomePage"));
const MyInterviewsPage = lazy(() => import("./pages/MyInterviewsPage"));
const RegisterPage = lazy(() => import("./pages/RegisterPage"));
const ReportsPage = lazy(() => import("./pages/ReportsPage"));
const SalaryPage = lazy(() => import("./pages/SalaryPage"));
const ScreeningDashboardPage = lazy(() => import("./pages/ScreeningDashboardPage"));
const ScreeningListPage = lazy(() => import("./pages/ScreeningListPage"));
const SetPasswordPage = lazy(() => import("./pages/SetPasswordPage"));
const SetupWizardPage = lazy(() => import("./pages/SetupWizardPage"));
const SuperAdminPage = lazy(() => import("./pages/SuperAdminPage"));
const ShortlistingDashboardPage = lazy(() => import("./pages/ShortlistingDashboardPage"));
const ShortlistingListPage = lazy(() => import("./pages/ShortlistingListPage"));
const UnifiedInboxPage = lazy(() => import("./pages/UnifiedInboxPage"));
// Part 15.6: pages for the new modules.
const PeoplePage = lazy(() => import("./pages/people/PeoplePage"));
const MyAvailabilityPage = lazy(() => import("./pages/interviews/MyAvailabilityPage"));
const InterviewersPage = lazy(() => import("./pages/interviews/InterviewersPage"));
const EmployeeProfilePage = lazy(() => import("./pages/people/EmployeeProfilePage"));
const OrgChartPage = lazy(() => import("./pages/people/OrgChartPage"));
const OnboardingDashboardPage = lazy(() => import("./pages/onboarding/OnboardingDashboardPage"));
const WelcomePortalPage = lazy(() => import("./pages/onboarding/WelcomePortalPage"));
const SalaryDetailsFormPage = lazy(() => import("./pages/salary/SalaryDetailsFormPage"));
const PerformancePage = lazy(() => import("./pages/performance/PerformancePage"));
const TeamPerformancePage = lazy(() => import("./pages/performance/TeamPerformancePage"));
const ReviewFormPage = lazy(() => import("./pages/performance/ReviewFormPage"));
const CompensationPage = lazy(() => import("./pages/performance/CompensationPage"));
const SuccessionPage = lazy(() => import("./pages/performance/SuccessionPage"));
const HelpdeskPage = lazy(() => import("./pages/servicedesk/HelpdeskPage"));
const HelpdeskQueuePage = lazy(() => import("./pages/servicedesk/HelpdeskQueuePage"));
const AssetsPage = lazy(() => import("./pages/servicedesk/AssetsPage"));
const ExitsPage = lazy(() => import("./pages/servicedesk/ExitsPage"));
const AnalyticsPage = lazy(() => import("./pages/insights/AnalyticsPage"));
const ReportBuilderPage = lazy(() => import("./pages/insights/ReportBuilderPage"));
const AgenciesPage = lazy(() => import("./pages/agency/AgenciesPage"));
const AgencyPortalPage = lazy(() => import("./pages/agency/AgencyPortalPage"));
const SettingsHomePage = lazy(() => import("./pages/settings/SettingsHomePage"));
const SettingsCategoryPage = lazy(() => import("./pages/settings/SettingsCategoryPage"));

const PageLoading = () => <CircularProgress sx={{ m: 4 }} aria-label="Loading" />;

// Part 17.9: old URLs redirect, keeping their filters (e.g. /directory?location=<office>).
function KeepQuery({ to, extra }: { to: string; extra?: string }) {
  const { search } = useLocation();
  const qs = [search.replace(/^\?/, ""), extra].filter(Boolean).join("&");
  return <Navigate to={`${to}${qs ? `?${qs}` : ""}`} replace />;
}

// An agency login (Part 15.6) only has the agency portal -- never the staff home.
function HomeRoute() {
  const { user } = useAuth();
  return (user?.role as string | undefined) === "agency" ? <Navigate to="/agency" replace /> : <HomePage />;
}

export default function App() {
  return (
    <I18nProvider>
    <ErrorBoundary>
      <BootstrapProvider>
        <AppThemeProvider>
          <BrowserRouter>
            <AuthProvider>
              <Suspense fallback={<PageLoading />}>
              <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
              <Route path="/set-password" element={<SetPasswordPage />} />
              <Route path="/superadmin" element={<SuperAdminPage />} />
              <Route path="/welcome" element={<WelcomePortalPage />} />
              <Route path="/welcome/:token" element={<WelcomePortalPage />} />
              <Route path="/salary-details/:token" element={<SalaryDetailsFormPage />} />
              <Route path="/careers" element={<CareersLayout />}>
                <Route index element={<CareersListPage />} />
                <Route path=":id" element={<CareersJobDetailPage />} />
                <Route path=":id/apply" element={<CareersApplyPage />} />
                <Route path=":id/thank-you" element={<CareersThankYouPage />} />
              </Route>
              <Route
                element={
                  <ProtectedRoute>
                    <MeBootstrapProvider>
                      <AppLayout />
                    </MeBootstrapProvider>
                  </ProtectedRoute>
                }
              >
                <Route index element={<HomeRoute />} />
                <Route path="/overview" element={<OverviewPage />} />
                <Route path="/jobs" element={<JobsPage />} />
                <Route path="/candidates" element={<Navigate to="/candidates/dashboard" replace />} />
                <Route path="/candidates/dashboard" element={<CandidatesDashboardPage />} />
                <Route path="/candidates/list" element={<CandidatesListPage />} />
                <Route path="/candidates/import" element={<CandidatesImportPage />} />
                <Route path="/candidates/:applicationId" element={<CandidateDetailPage />} />
                <Route path="/screening" element={<Navigate to="/screening/dashboard" replace />} />
                <Route path="/screening/dashboard" element={<ScreeningDashboardPage />} />
                <Route path="/screening/list" element={<ScreeningListPage />} />
                <Route path="/shortlisting" element={<Navigate to="/shortlisting/dashboard" replace />} />
                <Route path="/shortlisting/dashboard" element={<ShortlistingDashboardPage />} />
                <Route path="/shortlisting/list" element={<ShortlistingListPage />} />
                <Route path="/interviews" element={<Navigate to="/interviews/dashboard" replace />} />
                <Route path="/interviews/dashboard" element={<InterviewsDashboardPage />} />
                <Route path="/interviews/list" element={<InterviewListPage />} />
                <Route path="/interviews/my" element={<MyInterviewsPage />} />
                <Route path="/interviews/availability" element={<MyAvailabilityPage />} />
                <Route path="/interviews/interviewers" element={<InterviewersPage />} />
                <Route path="/hr-inbox" element={<HrInboxListPage />} />
                <Route path="/candidate-emails" element={<HrInboxListPage />} />
                <Route path="/approvals" element={<UnifiedInboxPage />} />
                <Route path="/salary" element={<SalaryPage />} />
                <Route path="/bgv" element={<BgvPage />} />
                <Route path="/offers" element={<OffersPage />} />
                <Route path="/agencies" element={<AgenciesPage />} />
                <Route path="/agency" element={<AgencyPortalPage />} />
                <Route path="/reports" element={<ReportsPage />} />
                <Route path="/reports/builder" element={<ReportBuilderPage />} />
                <Route path="/analytics" element={<AnalyticsPage />} />
                <Route path="/people" element={<PeoplePage />} />
                <Route path="/people/:employeeId" element={<EmployeeProfilePage />} />
                <Route path="/employees" element={<KeepQuery to="/people" extra="view=hr" />} />
                <Route path="/employees/:employeeId" element={<EmployeeProfilePage />} />
                <Route path="/directory" element={<KeepQuery to="/people" />} />
                <Route path="/org-chart" element={<OrgChartPage />} />
                <Route path="/onboarding" element={<OnboardingDashboardPage />} />
                <Route path="/performance" element={<PerformancePage />} />
                <Route path="/performance/team" element={<TeamPerformancePage />} />
                <Route path="/performance/review/:reviewId" element={<ReviewFormPage />} />
                <Route path="/compensation" element={<CompensationPage />} />
                <Route path="/succession" element={<SuccessionPage />} />
                <Route path="/helpdesk" element={<HelpdeskPage />} />
                <Route path="/helpdesk/queue" element={<HelpdeskQueuePage />} />
                <Route path="/assets" element={<AssetsPage />} />
                <Route path="/exits" element={<ExitsPage />} />
                <Route path="/setup" element={<SetupWizardPage />} />
                <Route path="/settings" element={<SettingsHomePage />} />
                <Route path="/settings/:category" element={<SettingsCategoryPage />} />
                <Route path="/settings/:category/:page" element={<SettingsCategoryPage />} />
              </Route>
              </Routes>
              </Suspense>
            </AuthProvider>
          </BrowserRouter>
        </AppThemeProvider>
      </BootstrapProvider>
    </ErrorBoundary>
    </I18nProvider>
  );
}
