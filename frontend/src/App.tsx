import CssBaseline from "@mui/material/CssBaseline";
import { Navigate, Route, BrowserRouter, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthContext";
import ProtectedRoute from "./auth/ProtectedRoute";
import AppLayout from "./layout/AppLayout";
import BgvPage from "./pages/BgvPage";
import CandidatesPage from "./pages/CandidatesPage";
import InterviewsPage from "./pages/InterviewsPage";
import JobsPage from "./pages/JobsPage";
import LoginPage from "./pages/LoginPage";
import OffersPage from "./pages/OffersPage";
import RegisterPage from "./pages/RegisterPage";
import ReportsPage from "./pages/ReportsPage";
import SalaryPage from "./pages/SalaryPage";
import ScreeningPage from "./pages/ScreeningPage";
import ShortlistingPage from "./pages/ShortlistingPage";

export default function App() {
  return (
    <>
      <CssBaseline />
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route
              element={
                <ProtectedRoute>
                  <AppLayout />
                </ProtectedRoute>
              }
            >
              <Route index element={<Navigate to="/jobs" replace />} />
              <Route path="/jobs" element={<JobsPage />} />
              <Route path="/candidates" element={<CandidatesPage />} />
              <Route path="/screening" element={<ScreeningPage />} />
              <Route path="/shortlisting" element={<ShortlistingPage />} />
              <Route path="/interviews" element={<InterviewsPage />} />
              <Route path="/salary" element={<SalaryPage />} />
              <Route path="/bgv" element={<BgvPage />} />
              <Route path="/offers" element={<OffersPage />} />
              <Route path="/reports" element={<ReportsPage />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </>
  );
}
