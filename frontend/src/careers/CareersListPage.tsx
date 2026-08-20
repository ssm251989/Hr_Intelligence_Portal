import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Grid from "@mui/material/Grid";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { useNavigate } from "react-router-dom";

import { extractErrorMessage, publicApi } from "../api/client";
import type { PublicJobRead } from "../api/types";
import { formatExperienceRange } from "../utils/experience";
import { categorizeSkills } from "../utils/skills";

export default function CareersListPage() {
  const navigate = useNavigate();
  const [jobs, setJobs] = useState<PublicJobRead[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    publicApi
      .listJobs()
      .then(setJobs)
      .catch((err) => setError(extractErrorMessage(err, "Failed to load open positions")));
  }, []);

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={1}>
        Open Positions
      </Typography>
      <Typography variant="body1" color="text.secondary" mb={4}>
        Join our team — explore current openings below.
      </Typography>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {jobs === null && !error ? (
        <Box display="flex" justifyContent="center" py={6}>
          <CircularProgress />
        </Box>
      ) : jobs && jobs.length === 0 ? (
        <Typography color="text.secondary">There are no open positions right now. Please check back soon.</Typography>
      ) : (
        <Grid container spacing={2}>
          {jobs?.map((job) => {
            const { mustHave, goodToHave } = categorizeSkills(job);
            return (
              <Grid key={job.id} size={{ xs: 12 }}>
                <Card sx={{ border: 1, borderColor: "divider", borderRadius: 2 }}>
                  <CardActionArea onClick={() => navigate(`/careers/${job.id}`)}>
                    <CardContent>
                      <Typography variant="h6">{job.title}</Typography>
                      <Stack
                        direction="row" spacing={1} flexWrap="wrap" useFlexGap mt={1}
                        mb={mustHave.length || goodToHave.length ? 1.5 : 0}
                      >
                        {job.department && <Chip label={job.department} size="small" />}
                        {job.location && <Chip label={job.location} size="small" variant="outlined" />}
                        {formatExperienceRange(job.experience_min_years, job.experience_max_years) && (
                          <Chip
                            label={formatExperienceRange(job.experience_min_years, job.experience_max_years)}
                            size="small"
                            variant="outlined"
                          />
                        )}
                        {(job.education_degree_level || job.education_field) && (
                          <Chip
                            label={[job.education_degree_level, job.education_field].filter(Boolean).join(" in ")}
                            size="small"
                            variant="outlined"
                          />
                        )}
                      </Stack>
                      {mustHave.length > 0 && (
                        <Typography variant="body2" color="text.secondary">
                          Required: {mustHave.join(", ")}
                        </Typography>
                      )}
                      {goodToHave.length > 0 && (
                        <Typography variant="body2" color="text.secondary">
                          Nice to have: {goodToHave.join(", ")}
                        </Typography>
                      )}
                    </CardContent>
                  </CardActionArea>
                </Card>
              </Grid>
            );
          })}
        </Grid>
      )}
    </Box>
  );
}
