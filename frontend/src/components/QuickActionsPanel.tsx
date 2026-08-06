import AddCircleOutlineIcon from "@mui/icons-material/AddCircleOutline";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import ContentCopyOutlinedIcon from "@mui/icons-material/ContentCopyOutlined";
import ArchiveOutlinedIcon from "@mui/icons-material/ArchiveOutlined";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";

const COMING_SOON_ACTIONS = [
  { label: "Bulk Import Jobs", icon: UploadFileOutlinedIcon },
  { label: "Duplicate Job", icon: ContentCopyOutlinedIcon },
  { label: "Archive Old Jobs", icon: ArchiveOutlinedIcon },
];

export default function QuickActionsPanel({ onCreateJob }: { onCreateJob: () => void }) {
  return (
    <Stack spacing={1.5}>
      <Button variant="contained" startIcon={<AddCircleOutlineIcon />} onClick={onCreateJob} fullWidth>
        Create New Job
      </Button>
      {COMING_SOON_ACTIONS.map(({ label, icon: Icon }) => (
        <Tooltip key={label} title="Coming soon" placement="right">
          <span>
            <Button variant="outlined" startIcon={<Icon />} disabled fullWidth>
              {label}
              <Chip label="Soon" size="small" sx={{ ml: 1 }} />
            </Button>
          </span>
        </Tooltip>
      ))}
    </Stack>
  );
}
