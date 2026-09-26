import { useT } from "../i18n";
import { StatusChip, type Tone } from "../ui-kit";

// backend/app/models/job_role.py JOB_TYPES -- colour + emoji + word (Part 15 B), never colour alone.
const JOB_TYPE_STYLE: Record<string, { tone: Tone; emoji: string; key: string }> = {
  "Full-time": { tone: "ok", emoji: "briefcase", key: "jobs.type.full_time" },
  "Part-time": { tone: "sky", emoji: "hourglass", key: "jobs.type.part_time" },
  Contract: { tone: "sun", emoji: "memo", key: "jobs.type.contract" },
};

export default function JobTypeChip({ jobType, size = "small" }: { jobType: string; size?: "small" | "medium" }) {
  const t = useT();
  const style = JOB_TYPE_STYLE[jobType];
  if (!style) return <StatusChip tone="muted" emoji="label" label={jobType} size={size} />;
  return <StatusChip tone={style.tone} emoji={style.emoji} label={t(style.key)} size={size} />;
}
