import type { ReactNode } from "react";
import InfoOutlinedIcon from "@mui/icons-material/InfoOutlined";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";

// Part 15 C: an (i) next to any field a new user may not understand. Keyboard-focusable;
// the text is also exposed to screen readers via aria-label.
export default function InfoTip({ text, label = "What does this mean?" }: { text: ReactNode; label?: string }) {
  return (
    <Tooltip title={text} enterTouchDelay={0} leaveTouchDelay={4000}>
      <IconButton size="small" aria-label={typeof text === "string" ? `${label} ${text}` : label} sx={{ p: 0.25, ml: 0.25, color: "text.secondary", verticalAlign: "middle" }}>
        <InfoOutlinedIcon sx={{ fontSize: 16 }} />
      </IconButton>
    </Tooltip>
  );
}
