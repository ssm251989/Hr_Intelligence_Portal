import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CircularProgress from "@mui/material/CircularProgress";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormLabel from "@mui/material/FormLabel";
import Radio from "@mui/material/Radio";
import RadioGroup from "@mui/material/RadioGroup";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useParams } from "react-router-dom";

import { ApiError, extractErrorMessage } from "../../api/client";
import { salaryFormApi, type SalaryFormView } from "../../api/salaryApi";
import { useBootstrap } from "../../bootstrap/BootstrapContext";
import { BrandMark, LanguagePicker } from "../../components/careers/PublicAuthLayout";
import MoneyField, { DaysField } from "../../components/salary/MoneyField";
import { useT } from "../../i18n";
import { FriendlyAnimation, FriendlyError, Illustration } from "../../ui-kit";

// Part 17.8: the candidate's own "Salary & joining details" form, opened from the email
// link (/salary-details/:token). Public -- no login, no auth header. Company name/mark come
// from the public branding (bootstrap), like the Welcome portal.

const str = (v: number | null | undefined) => (v == null ? "" : String(Math.round(v)));

export default function SalaryDetailsFormPage() {
  const f = useTheme().palette.fresh;
  const t = useT();
  const { branding } = useBootstrap();
  const { token = "" } = useParams<{ token: string }>();

  const [view, setView] = useState<SalaryFormView | null>(null);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [current, setCurrent] = useState("");
  const [expected, setExpected] = useState("");
  const [notice, setNotice] = useState("");
  const [relocate, setRelocate] = useState<"" | "yes" | "no">("");
  const [joining, setJoining] = useState("");
  // Part 18.12: offers in hand + payslip (only when Settings ask for them)
  const [offers, setOffers] = useState("");
  const [bestOffer, setBestOffer] = useState("");
  const [payslips, setPayslips] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<unknown>(null);
  const [done, setDone] = useState(false);

  const load = useCallback(() => {
    if (!token) return;
    setLoadError(null);
    salaryFormApi
      .view(token)
      .then((v) => {
        setView(v);
        setCurrent(str(v.current_ctc));
        setExpected(str(v.expected_ctc));
        setNotice(v.notice_period_days == null ? "" : String(v.notice_period_days));
        setRelocate(v.willing_to_relocate == null ? "" : v.willing_to_relocate ? "yes" : "no");
        setPayslips(v.payslips ?? 0);
      })
      .catch(setLoadError);
  }, [token]);

  useEffect(load, [load]);

  const shell = (children: ReactNode) => (
    <Box sx={{ minHeight: "100vh", bgcolor: f.ground, display: "flex", flexDirection: "column" }}>
      <Box component="header" sx={{ bgcolor: f.surface, boxShadow: f.shadow }}>
        <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={2} sx={{ maxWidth: 640, mx: "auto", px: 2, py: 1.5 }}>
          <BrandMark size={34} />
          <LanguagePicker />
        </Stack>
      </Box>
      <Box component="main" sx={{ width: "100%", maxWidth: 640, mx: "auto", px: 2, py: { xs: 2.5, md: 4 }, flex: 1 }}>{children}</Box>
      <Box component="footer" sx={{ py: 2.5, px: 2, textAlign: "center", color: f.muted, fontSize: 13 }}>
        {branding?.support_contact ? t("salaryForm.footer_help", { contact: branding.support_contact }) : t("salaryForm.footer_plain")}
      </Box>
    </Box>
  );

  // 404 -> the link isn't valid; 410 -> the server's own friendly words (already answered / expired).
  const deadLink = (err: unknown): ReactNode | null => {
    if (!token || (err instanceof ApiError && (err.status === 404 || err.status === 410))) {
      const gone = err instanceof ApiError && err.status === 410;
      const answered = gone && /already/i.test(extractErrorMessage(err, ""));
      return shell(
        <Card sx={{ p: { xs: 2.5, md: 4 }, textAlign: "center" }}>
          {answered ? <FriendlyAnimation name="success" size={110} label={t("salaryForm.done_title")} /> : <Illustration name="access-denied" height={140} />}
          <Typography component="h1" sx={{ fontWeight: 800, fontSize: 22, mt: 2 }}>
            {gone ? extractErrorMessage(err, t("salaryForm.gone")) : t("salaryForm.invalid")}
          </Typography>
          <Typography sx={{ color: f.muted, mt: 1, maxWidth: "48ch", mx: "auto" }}>
            {answered ? t("salaryForm.answered_hint") : t("salaryForm.invalid_hint")}
          </Typography>
          {!answered && branding?.support_contact && (
            <Button variant="contained" sx={{ mt: 2 }} href={`mailto:${branding.support_contact}`}>{t("salaryForm.email_hr")}</Button>
          )}
        </Card>,
      );
    }
    return null;
  };

  const dead = deadLink(loadError) ?? deadLink(submitError);
  if (dead) return dead;

  if (loadError) {
    return shell(<FriendlyError what={t("salaryForm.load_failed")} fix={t("salaryForm.load_failed_fix")} onRetry={load} />);
  }

  if (!view) {
    return shell(
      <Box sx={{ display: "grid", placeItems: "center", py: 8 }} role="status" aria-label={t("salaryForm.loading")}>
        <CircularProgress />
      </Box>,
    );
  }

  if (done) {
    return shell(
      <Card sx={{ p: { xs: 2.5, md: 4 }, textAlign: "center" }} role="status">
        <FriendlyAnimation name="success" size={130} label={t("salaryForm.done_title")} />
        <Typography component="h1" sx={{ fontWeight: 800, fontSize: 24, mt: 1 }}>{t("salaryForm.done_title")}</Typography>
        <Typography sx={{ color: f.muted, mt: 1, maxWidth: "46ch", mx: "auto" }}>
          {view.job_title ? t("salaryForm.done_hint_job", { job: view.job_title }) : t("salaryForm.done_hint")}
        </Typography>
      </Card>,
    );
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!current || !expected || notice === "") {
      setProblem(t("salaryForm.need_all"));
      return;
    }
    if (Number(notice) > 365) {
      setProblem(t("salaryApply.notice_too_long"));
      return;
    }
    setProblem(null);
    setSubmitError(null);
    setSaving(true);
    try {
      await salaryFormApi.submit(token, {
        current_ctc: Number(current),
        expected_ctc: Number(expected),
        notice_period_days: Number(notice),
        willing_to_relocate: relocate === "" ? null : relocate === "yes",
        earliest_joining_date: joining || null,
        offers_in_hand: view.ask_offers && offers !== "" ? Number(offers) : null,
        best_offer_ctc: view.ask_offers && bestOffer ? Number(bestOffer) : null,
      });
      setDone(true);
    } catch (err) {
      setSubmitError(err);
    } finally {
      setSaving(false);
    }
  };

  const name = view.candidate_first_name?.trim();

  return shell(
    <Card sx={{ p: { xs: 2.5, sm: 4 } }}>
      <Typography component="h1" sx={{ fontWeight: 800, fontSize: { xs: 24, sm: 28 } }}>
        {name ? t("salaryForm.hi", { name }) : t("salaryForm.hi_plain")}
      </Typography>
      <Typography sx={{ color: f.muted, mt: 0.75, mb: 3 }}>
        {view.job_title ? t("salaryForm.intro_job", { job: view.job_title }) : t("salaryForm.intro")}
      </Typography>

      <Box component="form" onSubmit={submit} noValidate>
        <Stack spacing={2.5}>
          {problem && <FriendlyError compact what={problem} fix={t("salaryForm.fix")} />}
          {submitError !== null && <FriendlyError compact error={submitError} />}

          <MoneyField label={t("salaryForm.current")} required value={current} onChange={setCurrent} />
          <MoneyField label={t("salaryForm.expected")} required value={expected} onChange={setExpected} />
          <DaysField label={t("salaryForm.notice")} required value={notice} onChange={setNotice} />

          <Box>
            <FormLabel id="relocate-label" sx={{ color: f.ink, fontWeight: 600, fontSize: 14 }}>{t("salaryForm.relocate")}</FormLabel>
            <RadioGroup row aria-labelledby="relocate-label" value={relocate} onChange={(e) => setRelocate(e.target.value as "yes" | "no")}>
              <FormControlLabel value="yes" control={<Radio />} label={t("salaryForm.yes")} />
              <FormControlLabel value="no" control={<Radio />} label={t("salaryForm.no")} />
            </RadioGroup>
          </Box>

          <TextField
            label={t("salaryForm.joining")}
            type="date"
            value={joining}
            onChange={(e) => setJoining(e.target.value)}
            fullWidth
            slotProps={{ inputLabel: { shrink: true } }}
            helperText={t("salaryForm.joining_hint")}
          />

          {view.ask_offers && (
            <Stack spacing={2}>
              <TextField label={t("salaryForm.offers")} type="number" value={offers} onChange={(e) => setOffers(e.target.value)} fullWidth
                helperText={t("salaryForm.offers_hint")} slotProps={{ htmlInput: { min: 0, max: 20 } }} />
              {Number(offers) > 0 && <MoneyField label={t("salaryForm.best_offer")} value={bestOffer} onChange={setBestOffer} />}
            </Stack>
          )}
          {view.ask_payslip && (
            <Box>
              <Button variant="outlined" component="label" disabled={uploading}>
                {uploading ? t("salaryForm.uploading") : t("salaryForm.payslip")}
                <input hidden type="file" accept=".pdf,.png,.jpg,.jpeg" onChange={async (e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file) return;
                  setUploading(true);
                  setUploadError(null);
                  try { setPayslips((await salaryFormApi.payslip(token, file)).count); } catch (err) { setUploadError(err); } finally { setUploading(false); }
                }} />
              </Button>
              <Typography sx={{ color: f.muted, fontSize: 13, mt: 0.5 }}>
                {payslips > 0 ? t("salaryForm.payslip_count", { count: payslips }) : t("salaryForm.payslip_hint")}
              </Typography>
              {uploadError !== null && <FriendlyError compact error={uploadError} />}
            </Box>
          )}

          <Button type="submit" variant="contained" size="large" disabled={saving}>
            {saving ? t("salaryForm.sending") : t("salaryForm.submit")}
          </Button>
          <Typography sx={{ color: f.muted, fontSize: 13, textAlign: "center" }}>{t("salaryForm.private_note")}</Typography>
        </Stack>
      </Box>
    </Card>,
  );
}
