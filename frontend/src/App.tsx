import CssBaseline from "@mui/material/CssBaseline";
import { Route, BrowserRouter, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import CareersApplyPage from "./careers/CareersApplyPage";
import CareersJobDetailPage from "./careers/CareersJobDetailPage";
import CareersLayout from "./careers/CareersLayout";
import CareersListPage from "./careers/CareersListPage";
import CareersThankYouPage from "./careers/CareersThankYouPage";
import ErrorBoundary from "./components/ErrorBoundary";
import AppLayout from "./layout/AppLayout";
import BgvPage from "./pages/BgvPage";
import CandidatesPage from "./pages/CandidatesPage";
import InterviewsPage from "./pages/InterviewsPage";
import JobsPage from "./pages/JobsPage";
import LoginPage from "./pages/LoginPage";
import OffersPage from "./pages/OffersPage";
import OverviewPage from "./pages/OverviewPage";
import RegisterPage from "./pages/RegisterPage";
import ReportsPage from "./pages/ReportsPage";
import SalaryPage from "./pages/SalaryPage";
import ScreeningPage from "./pages/ScreeningPage";
import SettingsPage from "./pages/SettingsPage";
import ShortlistingPage from "./pages/ShortlistingPage";

export default function App() {
  return (
    <ErrorBoundary>
      <CssBaseline />
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
                  <AppLayout />
                </ProtectedRoute>
              }
            >
              <Route index element={<OverviewPage />} />
              <Route path="/jobs" element={<JobsPage />} />
              <Route path="/candidates" element={<CandidatesPage />} />
              <Route path="/screening" element={<ScreeningPage />} />
              <Route path="/shortlisting" element={<ShortlistingPage />} />
              <Route path="/interviews" element={<InterviewsPage />} />
              <Route path="/salary" element={<SalaryPage />} />
              <Route path="/bgv" element={<BgvPage />} />
              <Route path="/offers" element={<OffersPage />} />
              <Route path="/reports" element={<ReportsPage />} />
              <Route path="/settings" element={<SettingsPage />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
