import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { Link as RouterLink, useParams } from "react-router-dom";

import { ApiError, extractErrorMessage, publicApi } from "../api/client";
import type { PublicJobRead } from "../api/types";
import { formatExperienceRange } from "../utils/experience";
import { categorizeSkills } from "../utils/skills";

export default function CareersJobDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [job, setJob] = useState<PublicJobRead | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    publicApi
      .getJob(id)
      .then(setJob)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          setNotFound(true);
        } else {
          setError(extractErrorMessage(err, "Failed to load this job"));
        }
      });
  }, [id]);

  if (notFound) {
    return (
      <Box>
        <Typography variant="h5" mb={2}>
          This position is no longer available.
        </Typography>
        <Button component={RouterLink} to="/careers" variant="contained">
          View open positions
        </Button>
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">{error}</Alert>;
  }

  if (!job) {
    return (
      <Box display="flex" justifyContent="center" py={6}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant="h4" fontWeight={700} mb={1}>
        {job.title}
      </Typography>
      <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap mb={3}>
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

      {(() => {
        const { mustHave, goodToHave } = categorizeSkills(job);
        if (mustHave.length === 0 && goodToHave.length === 0) return null;
        return (
          <Box mb={3}>
            <Typography variant="subtitle2" gutterBottom>
              Skills
            </Typography>
            <Stack spacing={1}>
              {mustHave.length > 0 && (
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
                  <Typography variant="caption" color="text.secondary">
                    Required:
                  </Typography>
                  {mustHave.map((skill) => (
                    <Chip key={`must-${skill}`} label={skill} size="small" />
                  ))}
                </Stack>
              )}
              {goodToHave.length > 0 && (
                <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
                  <Typography variant="caption" color="text.secondary">
                    Nice to have:
                  </Typography>
                  {goodToHave.map((skill) => (
                    <Chip key={`good-${skill}`} label={skill} size="small" variant="outlined" />
                  ))}
                </Stack>
              )}
            </Stack>
          </Box>
        );
      })()}

      {job.preferred_certifications && job.preferred_certifications.length > 0 && (
        <Box mb={3}>
          <Typography variant="subtitle2" gutterBottom>
            Preferred Certifications
          </Typography>
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {job.preferred_certifications.map((cert) => (
              <Chip key={cert} label={cert} size="small" variant="outlined" />
            ))}
          </Stack>
        </Box>
      )}

      {job.jd_text && (
        <Box mb={4}>
          <Typography variant="body1" sx={{ whiteSpace: "pre-wrap" }}>
            {job.jd_text}
          </Typography>
        </Box>
      )}

      <Button component={RouterLink} to={`/careers/${job.id}/apply`} variant="contained" size="large">
        Apply Now
      </Button>
    </Box>
  );
}
