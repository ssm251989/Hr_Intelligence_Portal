import CssBaseline from "@mui/material/CssBaseline";
import { Navigate, Route, BrowserRouter, Routes } from "react-router-dom";

import AppLayout from "./layout/AppLayout";
import BgvPage from "./pages/BgvPage";
import CandidatesPage from "./pages/CandidatesPage";
import ComingSoonPage from "./pages/ComingSoonPage";
import InterviewsPage from "./pages/InterviewsPage";
import JobsPage from "./pages/JobsPage";
import SalaryPage from "./pages/SalaryPage";
import ScreeningPage from "./pages/ScreeningPage";
import ShortlistingPage from "./pages/ShortlistingPage";

export default function App() {
  return (
    <>
      <CssBaseline />
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route index element={<Navigate to="/jobs" replace />} />
            <Route path="/jobs" element={<JobsPage />} />
            <Route path="/candidates" element={<CandidatesPage />} />
            <Route path="/screening" element={<ScreeningPage />} />
            <Route path="/shortlisting" element={<ShortlistingPage />} />
            <Route path="/interviews" element={<InterviewsPage />} />
            <Route path="/salary" element={<SalaryPage />} />
            <Route path="/bgv" element={<BgvPage />} />
            <Route path="/offers" element={<ComingSoonPage title="Offers" />} />
            <Route path="/reports" element={<ComingSoonPage title="Reports" />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </>
  );
}
