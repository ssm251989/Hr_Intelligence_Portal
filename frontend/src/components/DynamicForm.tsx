import { useEffect, useMemo, useState } from "react";
import jsonLogic from "json-logic-js";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Checkbox from "@mui/material/Checkbox";
import CircularProgress from "@mui/material/CircularProgress";
import FormControl from "@mui/material/FormControl";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormHelperText from "@mui/material/FormHelperText";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { metadataApi } from "../api/client";

// Part 6 section 2: `<DynamicForm entity= context= />` renders whatever
// GET /api/v1/metadata/form-layouts/{entity}/{context} returns (a layout's own
// sections_json + that entity's active custom_field_defs) -- no page ever hand-codes a
// custom field's input again. This component renders the CUSTOM fields only (grouped by
// section) -- a layout's own `sections_json` describing standard fields is data the
// caller's own page already has real inputs for, not something DynamicForm re-renders.
// Supports the common field types with a real MUI input each; `file`/
// `lookup`/`formula` are scoped down to a labeled read-only/placeholder row (see each
// case below) rather than a full upload widget / searchable-entity picker / live formula
// evaluator, which need infrastructure (real file storage, a generic entity-search API,
// a formula engine) this part doesn't build.

export interface CustomFieldMeta {
  code: string;
  label_i18n: Record<string, string>;
  type: string;
  validation: { options?: string[]; min?: number; max?: number; pattern?: string } | null;
  default: unknown;
  required_condition: object | null;
  visible_condition: object | null;
  section: string | null;
  order: number;
  sensitive: boolean;
}

interface LayoutResponse {
  entity: string;
  context: string;
  sections: { name?: string; fields?: string[] }[];
  custom_fields: CustomFieldMeta[];
}

export interface DynamicFormProps {
  entity: string;
  context: string;
  locale?: string;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  errors?: Record<string, string>;
}

function fieldLabel(field: CustomFieldMeta, locale: string): string {
  return field.label_i18n[locale] || field.label_i18n.en || field.code;
}

function FieldInput({ field, value, onChange, locale }: { field: CustomFieldMeta; value: unknown; onChange: (v: unknown) => void; locale: string }) {
  const label = fieldLabel(field, locale);

  switch (field.type) {
    case "bool":
      return <FormControlLabel control={<Checkbox checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />} label={label} />;
    case "number":
    case "decimal":
    case "currency":
      return (
        <TextField
          size="small" label={label} type="number" value={value ?? ""}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        />
      );
    case "date":
      return <TextField size="small" label={label} type="date" InputLabelProps={{ shrink: true }} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
    case "datetime":
      return <TextField size="small" label={label} type="datetime-local" InputLabelProps={{ shrink: true }} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
    case "longtext":
      return <TextField size="small" label={label} multiline minRows={3} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
    case "picklist":
      return (
        <FormControl size="small">
          <InputLabel id={`${field.code}-label`}>{label}</InputLabel>
          <Select labelId={`${field.code}-label`} label={label} displayEmpty value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)}>
            <MenuItem value="">
              <em>--</em>
            </MenuItem>
            {(field.validation?.options ?? []).map((opt) => (
              <MenuItem key={opt} value={opt}>
                {opt}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      );
    case "multipicklist": {
      const selected = Array.isArray(value) ? (value as string[]) : [];
      return (
        <FormControl size="small">
          <InputLabel id={`${field.code}-label`}>{label}</InputLabel>
          <Select
            labelId={`${field.code}-label`} label={label} multiple displayEmpty value={selected}
            onChange={(e) => onChange(typeof e.target.value === "string" ? e.target.value.split(",") : e.target.value)}
            renderValue={(v) => (v as string[]).join(", ") || "--"}
          >
            {(field.validation?.options ?? []).map((opt) => (
              <MenuItem key={opt} value={opt}>
                {opt}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
      );
    }
    case "email":
      return <TextField size="small" label={label} type="email" value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
    case "url":
      return <TextField size="small" label={label} type="url" value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
    case "phone":
      return <TextField size="small" label={label} type="tel" value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
    case "file":
      return (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {label}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            File upload isn't wired to a real storage backend yet -- enter a file reference/URL for now.
          </Typography>
          <TextField size="small" fullWidth value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />
        </Box>
      );
    case "formula":
      return (
        <Box>
          <Typography variant="body2" fontWeight={600}>
            {label}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {value != null ? String(value) : "(computed)"}
          </Typography>
        </Box>
      );
    case "user":
    case "employee":
    case "lookup":
      return (
        <TextField
          size="small" label={`${label} (ID)`} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)}
          helperText="No searchable picker wired yet -- enter the exact ID for now."
        />
      );
    default:
      return <TextField size="small" label={label} value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }
}

export default function DynamicForm({ entity, context, locale = "en", values, onChange, errors = {} }: DynamicFormProps) {
  const [layout, setLayout] = useState<LayoutResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    metadataApi
      .effectiveLayout(entity, context)
      .then((response) => setLayout(response as LayoutResponse))
      .catch(() => setError("Failed to load form layout"))
      .finally(() => setLoading(false));
  }, [entity, context]);

  const evalContext = useMemo(() => ({ ...values }), [values]);

  if (loading) return <CircularProgress size={24} />;
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!layout) return null;

  const bySection = new Map<string, CustomFieldMeta[]>();
  for (const field of [...layout.custom_fields].sort((a, b) => a.order - b.order)) {
    const key = field.section || "General";
    if (!bySection.has(key)) bySection.set(key, []);
    bySection.get(key)!.push(field);
  }

  return (
    <Stack spacing={3}>
      {[...bySection.entries()].map(([sectionName, fields]) => (
        <Box key={sectionName}>
          <Typography variant="subtitle2" mb={1}>
            {sectionName}
          </Typography>
          <Stack spacing={2}>
            {fields.map((field) => {
              const visible = field.visible_condition ? Boolean(jsonLogic.apply(field.visible_condition, evalContext)) : true;
              if (!visible) return null;
              const required = field.required_condition ? Boolean(jsonLogic.apply(field.required_condition, evalContext)) : false;
              const fieldError = errors[field.code];
              return (
                <Box key={field.code}>
                  <FieldInput
                    field={field}
                    value={values[field.code]}
                    onChange={(v) => onChange({ ...values, [field.code]: v })}
                    locale={locale}
                  />
                  {required && <FormHelperText>Required</FormHelperText>}
                  {fieldError && <FormHelperText error>{fieldError}</FormHelperText>}
                </Box>
              );
            })}
          </Stack>
        </Box>
      ))}
      {layout.custom_fields.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No custom fields defined for {entity}/{context}.
        </Typography>
      )}
    </Stack>
  );
}
