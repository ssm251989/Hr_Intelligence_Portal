import TextField from "@mui/material/TextField";

import { indianNumber } from "../../api/salaryApi";
import { useT } from "../../i18n";

// Part 17.8: a yearly-amount field. Digits only; the helper line repeats the number in
// Indian grouping as the person types ("= 12,00,000 a year") so a missing zero is easy to spot.
export default function MoneyField({
  label, value, onChange, required, helper, size, autoFocus, disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  helper?: string;
  size?: "small" | "medium";
  autoFocus?: boolean;
  disabled?: boolean;
}) {
  const t = useT();
  const shown = indianNumber(value);
  return (
    <TextField
      label={label}
      value={value}
      onChange={(e) => onChange(e.target.value.replace(/[^\d]/g, "").slice(0, 10))}
      required={required}
      fullWidth
      size={size}
      autoFocus={autoFocus}
      disabled={disabled}
      slotProps={{ htmlInput: { inputMode: "numeric", pattern: "[0-9]*" } }}
      helperText={shown ? t("salaryApply.money_echo", { amount: shown }) : helper ?? t("salaryApply.money_hint")}
    />
  );
}

/** Digits-only days field (0-365). */
export function DaysField({
  label, value, onChange, required, size, disabled,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  required?: boolean;
  size?: "small" | "medium";
  disabled?: boolean;
}) {
  const t = useT();
  return (
    <TextField
      label={label}
      value={value}
      onChange={(e) => onChange(e.target.value.replace(/[^\d]/g, "").slice(0, 3))}
      required={required}
      fullWidth
      size={size}
      disabled={disabled}
      error={value !== "" && Number(value) > 365}
      slotProps={{ htmlInput: { inputMode: "numeric", pattern: "[0-9]*" } }}
      helperText={value !== "" && Number(value) > 365 ? t("salaryApply.notice_too_long") : t("salaryApply.notice_hint")}
    />
  );
}
