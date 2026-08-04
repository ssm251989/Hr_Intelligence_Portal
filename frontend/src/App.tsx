import CssBaseline from "@mui/material/CssBaseline";
import { Navigate, Route, BrowserRouter, Routes } from "react-router-dom";

import AppLayout from "./layout/AppLayout";
import CandidatesPage from "./pages/CandidatesPage";
import ComingSoonPage from "./pages/ComingSoonPage";
import JobsPage from "./pages/JobsPage";
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
            <Route path="/interviews" element={<ComingSoonPage title="Interviews" />} />
            <Route path="/salary" element={<ComingSoonPage title="Salary" />} />
            <Route path="/bgv" element={<ComingSoonPage title="BGV" />} />
            <Route path="/offers" element={<ComingSoonPage title="Offers" />} />
            <Route path="/reports" element={<ComingSoonPage title="Reports" />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </>
  );
}
