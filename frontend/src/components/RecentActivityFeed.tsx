import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import CircularProgress from "@mui/material/CircularProgress";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import Typography from "@mui/material/Typography";

import { extractErrorMessage, reportsApi } from "../api/client";
import type { RecentActivityItem } from "../api/types";

function timeAgo(isoTimestamp: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(isoTimestamp).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export default function RecentActivityFeed({
  limit = 10,
  refreshSignal = 0,
  dense = false,
}: {
  limit?: number;
  refreshSignal?: number;
  dense?: boolean;
}) {
  const [items, setItems] = useState<RecentActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    reportsApi
      .recentActivity(limit)
      .then((res) => setItems(res.items))
      .catch((err) => setError(extractErrorMessage(err, "Failed to load recent activity")))
      .finally(() => setLoading(false));
  }, [limit, refreshSignal]);

  if (loading) {
    return <CircularProgress size={20} />;
  }

  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }

  if (items.length === 0) {
    return (
      <Typography color="text.secondary" variant="body2">
        No recent activity yet.
      </Typography>
    );
  }

  return (
    <List dense={dense} disablePadding>
      {items.map((item) => (
        <ListItem key={item.id} disableGutters divider>
          <ListItemText
            primary={item.message}
            secondary={timeAgo(item.created_at)}
            slotProps={{ primary: { variant: "body2" }, secondary: { variant: "caption" } }}
          />
        </ListItem>
      ))}
    </List>
  );
}
