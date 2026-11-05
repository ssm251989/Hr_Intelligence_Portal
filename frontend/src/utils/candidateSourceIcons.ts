import type { SvgIconComponent } from "@mui/icons-material";
import Brightness7OutlinedIcon from "@mui/icons-material/Brightness7Outlined";
import BusinessCenterOutlinedIcon from "@mui/icons-material/BusinessCenterOutlined";
import LanguageOutlinedIcon from "@mui/icons-material/LanguageOutlined";
import LinkedInIcon from "@mui/icons-material/LinkedIn";
import PersonAddAltOutlinedIcon from "@mui/icons-material/PersonAddAltOutlined";
import SearchIcon from "@mui/icons-material/Search";
import UploadFileOutlinedIcon from "@mui/icons-material/UploadFileOutlined";
import WorkOutlineIcon from "@mui/icons-material/WorkOutline";

// Shared between the Import wizard's source picker and the Candidates Dashboard's Data
// Sources panel -- both display the same five sourcing platforms, so their icon/color
// choices live here once rather than being defined (and drifting) independently in each.
//
// Only set for the five real named sourcing platforms, each tinted with an approximation
// of that platform's own brand color -- identifying the real service, never implying a
// partnership or fabricating ownership of its mark. LinkedIn is the one source with a real
// official brand icon already shipped in @mui/icons-material; the rest (Naukri, Indeed,
// Monster, Shine) have no dedicated icon in that library, so they get a reasonable
// fallback glyph instead of an invented logo. Career Portal / Local Import are this app's
// own features, not third-party platforms, so they're intentionally absent here.
export const CANDIDATE_SOURCE_ICON: Partial<Record<string, SvgIconComponent>> = {
  linkedin: LinkedInIcon,
  naukri: WorkOutlineIcon, // approximate -- no official mark available in this icon library
  indeed: SearchIcon, // search glyph fits a job-search engine
  monster: BusinessCenterOutlinedIcon,
  shine: Brightness7OutlinedIcon, // sun glyph nods to the name, not a copied logo
};

export const CANDIDATE_SOURCE_COLOR: Partial<Record<string, string>> = {
  linkedin: "#0A66C2", // LinkedIn's real brand blue
  naukri: "#0E5C5C", // approximate dark teal
  indeed: "#2557A7", // approximate Indeed blue
  monster: "#7B2CBF", // approximate Monster purple
  shine: "#F5821F", // approximate warm orange
};

// career_portal/local_import are this app's own features, not third-party platforms, so
// they're deliberately absent from the maps above (which only approximate real brands).
// Colors here echo the stat cards representing the same buckets elsewhere on the
// Candidates Dashboard (From Career Portals / Manually Added).
export const CANDIDATE_APP_FEATURE_ICON: Partial<Record<string, SvgIconComponent>> = {
  career_portal: LanguageOutlinedIcon,
  local_import: UploadFileOutlinedIcon,
  // Recruiter-uploaded via the Candidates List page's "Upload Resume" button -- same icon
  // that button itself uses, so the two visually read as the same action/source.
  manual: PersonAddAltOutlinedIcon,
};
export const CANDIDATE_APP_FEATURE_COLOR: Partial<Record<string, string>> = {
  career_portal: "#1baf7a",
  local_import: "#eda100",
};

export function candidateSourceIcon(source: string): SvgIconComponent | undefined {
  return CANDIDATE_SOURCE_ICON[source] ?? CANDIDATE_APP_FEATURE_ICON[source];
}

export function candidateSourceIconColor(source: string): string | undefined {
  return CANDIDATE_SOURCE_COLOR[source] ?? CANDIDATE_APP_FEATURE_COLOR[source];
}
