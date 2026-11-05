import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";

import { useT } from "../../i18n";
import { Emoji } from "../../ui-kit";
import { printReport } from "./reportExport";

// Part 15.4 Reports (R4): the same two quiet buttons under every fixed report.
export default function ExportBar({ onCsv, disabled }: { onCsv: () => void; disabled?: boolean }) {
  const t = useT();
  return (
    <Stack direction="row" spacing={1} data-print-hide sx={{ flexWrap: "wrap", rowGap: 1 }}>
      <Button variant="outlined" size="small" onClick={onCsv} disabled={disabled} startIcon={<Emoji name="page" size={16} />}>
        {t("reports.export.csv")}
      </Button>
      <Button variant="outlined" size="small" onClick={printReport} disabled={disabled} startIcon={<Emoji name="memo" size={16} />}>
        {t("reports.export.pdf")}
      </Button>
    </Stack>
  );
}
