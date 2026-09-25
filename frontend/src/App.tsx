import { Navigate, Route, BrowserRouter, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import { BootstrapProvider } from "./bootstrap/BootstrapContext";
import { MeBootstrapProvider } from "./bootstrap/MeBootstrapContext";
import { AppThemeProvider } from "./theme/ThemeModeContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import CareersApplyPage from "./careers/CareersApplyPage";
import CareersJobDetailPage from "./careers/CareersJobDetailPage";
import CareersLayout from "./careers/CareersLayout";
import CareersListPage from "./careers/CareersListPage";
import CareersThankYouPage from "./careers/CareersThankYouPage";
import ErrorBoundary from "./components/ErrorBoundary";
import AppLayout from "./layout/AppLayout";
import BgvPage from "./pages/BgvPage";
import CandidateDetailPage from "./pages/CandidateDetailPage";
import CandidatesDashboardPage from "./pages/CandidatesDashboardPage";
import CandidatesImportPage from "./pages/CandidatesImportPage";
import CandidatesListPage from "./pages/CandidatesListPage";
import HrInboxListPage from "./pages/HrInboxListPage";
import InterviewListPage from "./pages/InterviewListPage";
import InterviewsDashboardPage from "./pages/InterviewsDashboardPage";
import JobsPage from "./pages/JobsPage";
import LoginPage from "./pages/LoginPage";
import OffersPage from "./pages/OffersPage";
import OverviewPage from "./pages/OverviewPage";
import RegisterPage from "./pages/RegisterPage";
import ReportsPage from "./pages/ReportsPage";
import SalaryPage from "./pages/SalaryPage";
import ScreeningDashboardPage from "./pages/ScreeningDashboardPage";
import ScreeningListPage from "./pages/ScreeningListPage";
import SettingsPage from "./pages/SettingsPage";
import ShortlistingDashboardPage from "./pages/ShortlistingDashboardPage";
import ShortlistingListPage from "./pages/ShortlistingListPage";
import UnifiedInboxPage from "./pages/UnifiedInboxPage";

export default function App() {
  return (
    <ErrorBoundary>
      <BootstrapProvider>
        <AppThemeProvider>
          <BrowserRouter>
            <AuthProvider>
              <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/register" element={<RegisterPage />} />
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
                <Route index element={<OverviewPage />} />
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
                <Route path="/hr-inbox" element={<HrInboxListPage />} />
                <Route path="/approvals" element={<UnifiedInboxPage />} />
                <Route path="/salary" element={<SalaryPage />} />
                <Route path="/bgv" element={<BgvPage />} />
                <Route path="/offers" element={<OffersPage />} />
                <Route path="/reports" element={<ReportsPage />} />
                <Route path="/settings" element={<SettingsPage />} />
              </Route>
              </Routes>
            </AuthProvider>
          </BrowserRouter>
        </AppThemeProvider>
      </BootstrapProvider>
    </ErrorBoundary>
  );
}
