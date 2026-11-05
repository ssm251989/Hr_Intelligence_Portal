import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
import Alert from "@mui/material/Alert";
import AlertTitle from "@mui/material/AlertTitle";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";

import { t } from "../i18n";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled UI error", error, info);
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.error) {
      return (
        <Box display="flex" alignItems="center" justifyContent="center" minHeight="100vh" p={3}>
          <Alert severity="error" sx={{ maxWidth: 480 }}>
            {/* Part 15 C: what happened + how to fix + the button that fixes it. */}
            <AlertTitle>{t("error.page_crashed")}</AlertTitle>
            {t("error.page_crashed_fix")}
            <Box mt={2} display="flex" gap={1}>
              <Button variant="contained" size="small" onClick={this.handleReload}>
                {t("action.reload")}
              </Button>
              <Button variant="outlined" size="small" href="/">
                {t("action.go_home")}
              </Button>
            </Box>
          </Alert>
        </Box>
      );
    }
    return this.props.children;
  }
}
