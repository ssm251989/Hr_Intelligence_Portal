import RefreshOutlinedIcon from "@mui/icons-material/RefreshOutlined";
import CircularProgress from "@mui/material/CircularProgress";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";

// One shared refresh control for every List/Dashboard page's toolbar -- `loading` is
// always the page's own existing fetch-in-flight flag (never a separate state this
// component invents), so the spinner/disabled state is exactly as accurate as whatever
// that page already tracks, and matches every other in-flight icon-button in this app
// (e.g. CandidatesListPage's resume-download button) rather than introducing a new one.
export default function RefreshButton({
  loading,
  onRefresh,
  label = "Refresh",
}: {
  loading: boolean;
  onRefresh: () => void;
  label?: string;
}) {
  return (
    <Tooltip title={label}>
      <span>
        <IconButton onClick={onRefresh} disabled={loading} size="small" aria-label={label}>
          {loading ? <CircularProgress size={18} /> : <RefreshOutlinedIcon fontSize="small" />}
        </IconButton>
      </span>
    </Tooltip>
  );
}
