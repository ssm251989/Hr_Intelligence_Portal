# Portal pages (Part 15 hand-over)

Who sees it = the permission that shows the page in the menu (system roles in
`backend/app/platform/iam/roles.py`). "Everyone" = any signed-in staff user. Super Admin
sees every staff page. Screenshots are light mode, in `docs/ui/screens/`.

| Page | URL | Who sees it | What it does | Screenshot |
|---|---|---|---|---|
| Sign in | `/login` | Public | Sign in, language picker, split layout with illustration | `login.png` |
| Register | `/register` | Public | Self-registration for recruiters / hiring managers / interviewers | `register.png` |
| Set password | `/set-password?token=` | Public (invite link) | First password for invited admins and agency users | `set-password.png` |
| Careers | `/careers` | Public | Job list with search/filters, benefits, FAQ | `careers.png` |
| Job detail / apply | `/careers/:id`, `/careers/:id/apply` | Public | Job description and short apply form | `careers-job.png` |
| Welcome portal | `/welcome/:token` | Pre-joiner (magic link) | Welcome video, progress bar, step cards, phone document upload, first-day agenda, buddy | `welcome.png` |
| Home | `/` | Everyone | Role-based home (HR / Manager / Employee), drag-and-resize boxes | `home.png` |
| Overview (old) | `/overview` | Everyone | The previous overview dashboard, kept | `overview.png` |
| My approvals | `/approvals` | Everyone | One inbox for everything waiting on me | `approvals.png` |
| Jobs | `/jobs` | Recruitment roles | Create, publish and track jobs | `jobs.png` |
| Candidates | `/candidates/dashboard`, `/candidates/list`, `/candidates/import` | Recruitment roles | Candidate dashboard, list with filters, resume import | `candidates.png` |
| Candidate profile | `/candidates/:applicationId` | Recruitment roles | One candidate's application, stage stepper, actions | `candidate-profile.png` |
| Screening | `/screening/dashboard`, `/screening/list` | Recruitment roles | AI screening results and review | `screening.png` |
| Shortlisting | `/shortlisting/dashboard`, `/shortlisting/list` | Recruitment roles | Compare, shortlist, reject with reason | `shortlisting.png` |
| Interviews | `/interviews/dashboard`, `/interviews/list`, `/interviews/my` | Recruitment roles, interviewers | Table / week calendar, my interviews, scorecards | `interviews.png` |
| HR Inbox | `/hr-inbox` | Recruitment roles | Candidate emails, assign to candidate, reply snippets | `hr-inbox.png` |
| Salary | `/salary` | Recruitment roles | Salary band check and approve / decline | `salary.png` |
| Background checks | `/bgv` | Recruitment roles | BGV checklist, mismatches, vendor timeline | `bgv.png` |
| Offers | `/offers` | Recruitment roles | Offer templates with live preview, sent -> signed timeline | `offers.png` |
| Agencies | `/agencies` | `recruitment.agency.view` (HR Admin, HRBP, Recruiter) | Add agencies, choose their jobs, invite their users, see who they sent | `agencies.png` |
| Agency portal | `/agency` | Agency users only (`agency` login) | Assigned open jobs, send a candidate, plain status of each one sent | `agency.png` |
| Reports | `/reports`, `/reports/builder` | Recruitment roles; builder needs analytics | Recruitment reports + drag-and-drop report builder with Excel/CSV/PDF | `reports.png` |
| Analytics | `/analytics` | `analytics.report.view` | Hiring Sankey, jobs by location, candidate heat-map, headcount map, scheduled reports | `analytics.png` |
| Onboarding | `/onboarding` | `onboarding.preboarding.view` | Joiner cards by joining date, readiness ring, daily digest | `onboarding.png` |
| Employees | `/employees` | `core_hr.employee.view` | Employee list with filters, add person | `employees.png` |
| Employee profile | `/employees/:id` | `core_hr.employee.view` | Header card + Personal / Job / Documents / History tabs, masked PAN/bank with reveal | `employee-profile.png` |
| People directory | `/directory` | `core_hr.employee.view` | Find people by department, location, skill | `directory.png` |
| Org chart | `/org-chart` | `core_hr.org.view` | Zoomable reporting tree with photos | `org-chart.png` |
| Performance | `/performance`, `/performance/team`, `/performance/review/:id` | Employees (own), managers, HR | Goals tree, check-ins, one-page review with autosave, team table, 9-box | `performance.png` |
| Compensation | `/compensation` | `compensation.planning.view` | Compensation grid with budget meter | `compensation.png` |
| Succession | `/succession` | `performance.succession.view` | Successors per key position | `succession.png` |
| Helpdesk | `/helpdesk`, `/helpdesk/queue` | Employees (raise/track), helpdesk agents (queue) | Raise a ticket with suggested answers; agent queue with response-time chips | `helpdesk.png` |
| Assets | `/assets` | Employees (mine), asset admins | Asset register with QR labels, catalogue requests, handover acknowledgement | `assets.png` |
| Exits | `/exits` | Employees (resign), HR (cases) | Resignation form, clearance board, exit interview, relieving letter status | `exits.png` |
| Setup | `/setup` | `platform.settings.configure` | Setup wizard checklist | `setup.png` |
| Settings | `/settings`, `/settings/:category/:page` | `platform.settings.view` | Settings home with search; branding, mailboxes, email templates, approvals, custom fields, roles, languages, media | `settings.png` |
| Super-admin console | `/superadmin` | Platform operators | Tenants, licences, health | `superadmin.png` |

## Part 18 pages (2026-09-28)

| Page | Route | Who | What it does | Screenshot |
|---|---|---|---|---|
| Locked module card | any page of a locked module | everyone (admins can unlock) | "… is locked - enter passcode" (18.4) | pending login |
| Settings > Advanced > Modules | `/settings/advanced/modules` | admins | modules on/off, lock/unlock, change passcode, lock settings (18.4, 18.5) | pending login |
| Jobs (health column + needs-attention table) | `/jobs` | recruiters | chips, health chip with reasons, sortable table; Close job (18.7, 18.8) | pending login |
| Settings > Integrations > Job boards | `/settings/integrations/job-boards` | admins | LinkedIn / Naukri / Indeed / Monster / Shine setup, test, disconnect (18.9) | pending login |
| Salary (table + side panel, Finance tab) | `/salary`, `/salary?tab=finance` | HR | all salary-stage candidates, decisions, department budgets dashboard (18.11-18.15) | pending login |
| BGV / Offers (all-candidates tables) | `/bgv`, `/offers` | HR | stage tables, joining-documents review, BGV decision, joining dates (18.11, 18.17-18.19) | pending login |
| Candidate: joining documents | `/documents/:token` | candidate (no login) | upload required documents (18.16) | pending (needs a live link) |
| Candidate: choose joining date | `/joining/:token` | candidate (no login) | pick one of 3 dates (18.19) | pending (needs a live link) |
| Settings > Hiring > Department budgets / Required documents / Contacts | `/settings/hiring/budgets`, `/documents`, `/contacts` | admins | 18.15, 18.16, 18.20 | pending login |
| Settings > People & access > Users | `/settings/people/users` | admins | invite, role, switch off/on, password reset (18.22) | pending login |
| Settings > Company > Offices | `/settings/company/offices` | admins | offices add/edit/delete + map (18.22) | pending login |
| Settings > Integrations > GenAI | `/settings/integrations/ai` | admins | key, test, models, features, prices, limits (18.23, 18.25) | pending login |
| GenAI usage | `/genai-usage` | admins / analytics | usage and cost by module, feature, person, day, candidate (18.24) | pending login |
| Public pages in light + dark | `/login`, `/careers`, `/status/:token` | everyone | 18.6 colour themes | `login-light/-dark.png`, `careers-light/-dark.png`, `candidate-status-light/-dark.png` |
