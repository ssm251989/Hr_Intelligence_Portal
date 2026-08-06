import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";
import Alert from "@mui/material/Alert";
import AlertTitle from "@mui/material/AlertTitle";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";

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
            <AlertTitle>Something went wrong</AlertTitle>
            This page hit an unexpected error and couldn't continue. Reloading usually fixes it.
            <Box mt={2}>
              <Button variant="outlined" size="small" onClick={this.handleReload}>
                Reload page
              </Button>
            </Box>
          </Alert>
        </Box>
      );
    }
    return this.props.children;
  }
}
