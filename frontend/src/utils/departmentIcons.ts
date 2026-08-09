import type { SvgIconComponent } from "@mui/icons-material";
import CampaignOutlinedIcon from "@mui/icons-material/CampaignOutlined";
import CodeOutlinedIcon from "@mui/icons-material/CodeOutlined";
import DesignServicesOutlinedIcon from "@mui/icons-material/DesignServicesOutlined";
import GavelOutlinedIcon from "@mui/icons-material/GavelOutlined";
import HandshakeOutlinedIcon from "@mui/icons-material/HandshakeOutlined";
import PaidOutlinedIcon from "@mui/icons-material/PaidOutlined";
import PeopleAltOutlinedIcon from "@mui/icons-material/PeopleAltOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import SmartToyOutlinedIcon from "@mui/icons-material/SmartToyOutlined";
import SupportAgentOutlinedIcon from "@mui/icons-material/SupportAgentOutlined";
import WorkOutlineIcon from "@mui/icons-material/WorkOutline";

// department is free text (see the create-job wizard's creatable dropdown), not a fixed
// enum -- this is a best-effort "does this look like an X department" keyword match, not
// an exhaustive taxonomy. Checked in order, first match wins.
const DEPARTMENT_ICON_RULES: Array<{ keywords: string[]; icon: SvgIconComponent }> = [
  {
    keywords: ["ai", "artificial intelligence", "automation anywhere", "automation", "rpa", "robotics"],
    icon: SmartToyOutlinedIcon,
  },
  {
    keywords: ["engineering", "engineer", "development", "developer", "software", "it", "tech", "data", "qa", "devops"],
    icon: CodeOutlinedIcon,
  },
  { keywords: ["sales", "business development"], icon: HandshakeOutlinedIcon },
  { keywords: ["marketing", "growth", "brand"], icon: CampaignOutlinedIcon },
  { keywords: ["hr", "human resources", "people", "talent", "recruit"], icon: PeopleAltOutlinedIcon },
  { keywords: ["finance", "accounting", "payroll"], icon: PaidOutlinedIcon },
  { keywords: ["legal", "compliance"], icon: GavelOutlinedIcon },
  { keywords: ["design", "ux", "ui"], icon: DesignServicesOutlinedIcon },
  { keywords: ["support", "customer success", "customer service"], icon: SupportAgentOutlinedIcon },
  { keywords: ["operations", "ops"], icon: SettingsOutlinedIcon },
];

// Generic "job" icon -- same one already used for the Jobs nav item -- for any
// unmapped or missing department.
export const DEFAULT_DEPARTMENT_ICON: SvgIconComponent = WorkOutlineIcon;

export function getDepartmentIcon(department?: string | null): SvgIconComponent {
  if (!department) return DEFAULT_DEPARTMENT_ICON;
  const normalized = department.toLowerCase();
  const rule = DEPARTMENT_ICON_RULES.find((entry) => entry.keywords.some((keyword) => normalized.includes(keyword)));
  return rule?.icon ?? DEFAULT_DEPARTMENT_ICON;
}
