import { lazy, Suspense } from "react";
import { Navigate, Route, BrowserRouter, Routes } from "react-router-dom";
import CircularProgress from "@mui/material/CircularProgress";

import { AuthProvider } from "./auth/AuthContext";
import { BootstrapProvider } from "./bootstrap/BootstrapContext";
import { MeBootstrapProvider } from "./bootstrap/MeBootstrapContext";
import { AppThemeProvider } from "./theme/ThemeModeContext";
import ProtectedRoute from "./auth/ProtectedRoute";
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
const SettingsPage = lazy(() => import("./pages/SettingsPage"));
const SuperAdminPage = lazy(() => import("./pages/SuperAdminPage"));
const ShortlistingDashboardPage = lazy(() => import("./pages/ShortlistingDashboardPage"));
const ShortlistingListPage = lazy(() => import("./pages/ShortlistingListPage"));
const UnifiedInboxPage = lazy(() => import("./pages/UnifiedInboxPage"));

const PageLoading = () => <CircularProgress sx={{ m: 4 }} aria-label="Loading" />;

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
                <Route index element={<HomePage />} />
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
                <Route path="/hr-inbox" element={<HrInboxListPage />} />
                <Route path="/approvals" element={<UnifiedInboxPage />} />
                <Route path="/salary" element={<SalaryPage />} />
                <Route path="/bgv" element={<BgvPage />} />
                <Route path="/offers" element={<OffersPage />} />
                <Route path="/reports" element={<ReportsPage />} />
                <Route path="/setup" element={<SetupWizardPage />} />
                <Route path="/settings" element={<SettingsPage />} />
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
