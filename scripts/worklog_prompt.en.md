# Archive today's work into the task manager

You are the automation agent. The input is an evidence file: what the user actually typed into local Claude sessions today, plus a filesystem scan of files changed today. Your job: record the **substantive work actually done** as **completed** tasks in the task manager.

## Inputs

The orchestrator passes: `evidence file path` and `date (YYYY-MM-DD)`. Read that file first.

## The two evidence sections

1. **Claude session section**: lines starting `-- HH:MM [project] session-id`, followed by the user's own words.
2. **File-change evidence**: starts with `## File changes`; a timestamp scan of the whole machine for files modified or created on that day, grouped by directory, each line tagged:
   - `[human]` — usually produced by a person
   - `[likely automated]` — cache / log / program output / batch / browser profile (reason in parentheses)
   - `[new]` — created today (may come from import, extraction, download)

Both sections describe the same work; **judge them together**. If the same piece of work appears in both, create one task only.

## How to use file-change evidence

- **A file changed ≠ work was done.** Only record changes that map to a concrete deliverable (document / code / data / figure / model / manuscript / media).
- `[likely automated]`: do **not** record by default. Only record when the session section or the diary shows the user was actually driving that work.
- `[new]` human media files (photos / videos / images in directories already tagged `[human]`): record as `📷 archive media`, **grouped by parent directory**:
  - Find the **common parent** of those media directories (e.g. `...\high-frequency\selfies` and `...\high-frequency\food` → `high-frequency`).
  - Create **one** task per parent: `📷 Organize media: <parent> (<subdirs joined by />, <N> files)`.
  - If only one directory is involved, use that directory: `📷 Organize media: <dir> (<N> files)`.
  - At most **4** media tasks per run; anything beyond, or small scattered batches (<5 files), merge into `📷 Organize other media (<N> files)`.
  - Skip paths that belong to auto-download projects or are tagged `[likely automated]`.
- **`## Directory changes` section**: entries were added/removed/renamed inside a directory (typical of tidying files, moving images, creating folders), without file timestamp changes. This is **weak evidence**: record one task only if it maps to a concrete organizing action (e.g. `📷 Organize image folder`); if you cannot tell what was done, do not record.
- Content for directory-change tasks: `auto-recorded from directory change: <dir> (<date>)`.
- A directory line marked "batch" or with a huge file count (dozens/hundreds of similar files): almost certainly program output — do not record.
- `[human]` changes to documents / code / data / manuscripts: prefer recording them, but **merge similar changes into one task** (e.g. "edit chapter 3", not one task per file).
- Content for file-change tasks: `auto-recorded from file change: <dir or filename> (<date>)`.
- If there is **no session evidence but clear human file changes**, still record them. **Do not** output `NO_WORK`.

## Steps

1. **Read the evidence** and judge session by session. **Split by deliverable; never compress a whole session into one task**: if a session produced several unrelated things (different deliverables/topics), summarize them into several tasks. Example: a 14:51–20:07 session wrote a weekly report, remade a graphical abstract, then revised a roadmap → that is **3 tasks**, not 1.
   - Rule: **different deliverable = different task** (different file / section / script / conclusion).
   - The same piece of work across several sessions, or appearing in both session and file evidence → merge into one.
   - Scattered `continue` / `ok` / `A` / pure-image messages do not become tasks; attach them to the work they belong to.
   - Group file evidence by "same directory / same theme" into one item, then dedupe against session evidence.
2. **Deduplicate**: call `{{LIST_COMPLETED}}` (startDate = 00:00 that day, endDate = 23:59 that day, timezone `{{TIMEZONE}}`) to get today's existing task titles. If an existing task already covers the same piece of work, **skip it**.

   ⚠️ **Exception: the same work continued later.** An existing task only covers its time window up to the moment it was created. If the evidence shows **later timestamps** for the same work (same file/directory changed again, or the session kept working on it after the task ended), **do not simply skip** — add it to a "to extend" list for step 3.5. The reverse also applies: if evidence shows the work actually started **earlier**, extend backwards as well.

   ⚠️ **Dedup at the level of "a piece of work", not "a session".** A session often contains several distinct deliverables (edited a script, wrote docs, fixed a bug, ran a migration); compare **each** against existing tasks. **Do not** mark the whole session as covered because one item matched.

   ⚠️ **Ignore a trailing `(n/N)` when comparing**: `💼 Collect application material (2/2)` and an existing `💼 Collect application material` are **different time segments of the same work**. Skip only the segment already covered; create the missing segment (still following step 5's numbering rule).

   ⚠️ **"Already exists" means this run's `{{LIST_COMPLETED}}` result only.** The `<!-- dida365:begin -->` block in the diary is written by this pipeline itself and **must not** be used as evidence of coverage (that self-reinforces and causes missed records).

## Step 3: add times to "manually added all-day tasks"

Users often create tasks by hand in the task manager and tick them complete directly. Those tasks have **all-day** dates (`isAllDay=true`, `startDate`/`dueDate` end with `T00:00:00`) and show up in the diary block without a time. This step converts them into timed tasks using **the task list already fetched in step 2** (do not query again).

**Targets** (all three must hold):
1. `status == 2` (completed)
2. `isAllDay == true`, or `startDate`/`dueDate` end with `T00:00:00`
3. `content` does **not** start with any auto-record prefix, **and** does not start with `manual entry:`
   (auto prefixes are listed in step 8; `manual entry:` means this step already handled it — skip for idempotency)

**How to compute**:
- Completion time = `createdTime` (the moment it was added, to the minute).
- ⚠️ **Cross-day exception**: if the task's planned day (`startDate` date) differs from the `createdTime` date — a to-do created in advance or recorded afterwards — using the creation time would move the task to another day. **Keep the planned day** and take only `HH:MM` from `createdTime`.
- Estimate duration by task type (keep in sync with `scripts/tools/manual_time_fix.py`):

  | Keyword match | Duration | Category |
  |---|---|---|
  | movie / screening / concert / theatre | 150 min | screening/show |
  | SEM / microscopy / characterization | 120 | characterization |
  | meeting / seminar / defense / lecture / review / discussion | 120 | meeting/report |
  | paper / writing / figure / plotting / diagram / manuscript / revision / submission | 180 | paper/figures |
  | experiment / pressing / wetting / cutting / preparation / brazing / coating | 120 | experiment |
  | simulation / modeling / CFD / COMSOL / ANSYS | 150 | simulation/modeling |
  | program / script / automation / code / deploy / debug / config | 120 | programming |
  | resume / application / assessment / interview / job search | 60 | job/materials |
  | reimbursement / bill / invoice / approval / request | 45 | finance/forms |
  | parcel / pickup / shipping / courier | 15 | parcels |
  | organize / archive / inventory / album / images | 60 | organizing |
  | haircut / shopping / order / top-up / bill payment | 30 | personal errands |
  | no match | 30 | general |

  Match top-down; **first hit wins**.
- Start time = completion time − duration; clamp to `00:05` if it lands before midnight.
- `dueDate` equals `completedTime`; `isAllDay=false`.

**Two-line content** (first line must start with `manual entry:` so step 8's refresh never touches it):
```
manual entry: completion = created time 2026-11-03 16:37; estimated 15 min (parcel) -> start 16:22
last updated: 2026-11-03 16:37
```
For the cross-day case, write the first line accordingly and keep the planned date.
The second line uses **that task's completion time**, not `UpdatedAt`.

**Submit**: one `{{UPDATE_TASKS}}`, each item only
`{id, projectId, content, startDate, dueDate, completedTime, isAllDay}`.
⚠️ Completion time must be in the past (a future value makes the task disappear from the completed list).

If nothing matches, do not call the tool; report `mt=0`.

## Step 3.5: continued work → extend existing tasks' time windows

This is where step 2's "to extend" list lands. Goal: **when the same work continues later, the time window must follow**, otherwise diary entries freeze at the first creation moment.

**Targets**: today's existing **auto-recorded tasks** (content first line is one of step 8's prefixes) with a matching timestamp for the same work. User-created tasks (empty content / `manual entry:` / anything else) are **never touched**.

**Matching (prefer not extending)**: must be the **same deliverable** — same filename, or different versions of the same figure/manuscript (`fig1_8_route.png` and `fig1_8_route_bak-*.png` count as the same; `report.docx` and `report_v2.pdf` count as the same), or the same batch of images in the same `_intermediate` / `figures_export` directory. "Both are about the paper today" or "the same session is still running" **do not count**. **If unsure, do not extend.**

**New window (three hard rules)**:
- **Endpoints must be evidenced**: new start/end may only use timestamps that actually appear in the evidence (file lines `HH:MM:SS`, session headers `HH:MM`). **Never** use `FallbackTime` as an end time — it is an upper bound, not evidence. No evidence = no extension.
- **Extend the end only; do not move the start earlier** (that smears a task across the whole day).
- **Only expand, except an endpoint with no evidence may shrink**: if a task's current end (or start) cannot be found anywhere in this run's evidence (typical: a previous run used `FallbackTime`), shrink it to an evidenced timestamp. Otherwise never shrink.
- **Numbered tasks (`(n/N)`): extend only the temporally closest one**. If the new evidence is near 18:34, extend `(2/2)`, not `(1/2)`. If the gap between segments is ≥2 hours, do not extend at all — that is a new segment for step 5.
- The end still must **not exceed** `FallbackTime` (future values disappear from the completed list).

**Evidence check every run**: for each auto-recorded task today, search the evidence for its current end `HH:MM`:
- Found on the **same deliverable's** file line (`HH:MM:SS`) or session header → supported, leave it.
- Not found → the end has no evidence; shrink to the latest real timestamp for that deliverable.
- A start clearly earlier than the earliest evidence, with hours of unrelated activity in between → shrink as well.

**Submit**: one `{{UPDATE_TASKS}}`, each item **only** `{id, projectId, startDate, dueDate, completedTime, isAllDay: false}`.
⚠️ **Do not send** `title` / `content` / `status` — touching content fights step 8; touching status can flip a completed task back to open.
⚠️ This step and step 8 are separate updates: **this step owns time fields, step 8 owns content only**. Do not merge them.
If nothing needs extending, do not call the tool; report `ext=0`.

4. **Filter** (be strict; better to miss than to invent):
   - **Record**: research/paper/simulation/experiment design, job search (applications/assessments/resume/recommendation letters), project setup and code, system and software troubleshooting, literature search and organization, reporting slides, purchasing/reimbursement, media archiving, institutional note-taking; and **anything backed by clear human file changes** (editing in Word/Origin/MATLAB/Photoshop counts even if the session never mentions it).
   - **Do not record**: pure chat and general questions (health, philosophy, gossip) unless they produced or changed a file; "look up X" with no action; interrupted/unfinished work; changes that are only cache/log/program data (see above).
   - If unsure: **do not record**. Fewer, accurate records beat invented ones.
5. **Create tasks** (must be two steps):
   - **First assign a time window to each task**:
     * session evidence `-- HH:MM` or `-- HH:MM-HH:MM` is that session's working window for the day;
     * every file/directory evidence line carries `HH:MM:SS`;
     * when merging several evidence lines for one task: **earliest as start, latest as end**;
     * no timestamp at all (e.g. only from handwritten diary lines or directory changes): use `FallbackTime` for both.
   - First `{{ADD_TASKS}}`, each item carries: `projectId="{{INBOX_PROJECT_ID}}"`, **`columnId="{{INBOX_COLUMN_ID}}"`** (the Inbox "ungrouped" column; without it the task is invisible in the list), `title`, `content`, `startDate`=`<date>T<start>:00{{TZ_OFFSET}}`, `dueDate`=`<date>T<end>:00{{TZ_OFFSET}}`, `timeZone="{{TIMEZONE}}"`, `isAllDay=false`.
   - Then `{{UPDATE_TASKS}}` with the returned `taskId`, each item `{id, projectId, status: 2, completedTime: "<date>T<end>:00{{TZ_OFFSET}}"}`.
   - ⚠️ `status`/`completedTime` on creation are **silently ignored**; the second call is mandatory.
   - **Same work across disjoint periods → number the tasks**: if the evidence splits into disjoint segments with **≥2 hours between them**, split into several tasks titled `(1/N)`, `(2/N)`… each with its own window. A gap **<2 hours** stays merged. Do not number ordinary tasks.
   - **Title format**: `<emoji> <action, ≤24 chars>` (media tasks may include a count).
   - **Content format**: one source line + newline + one `last updated:` line. The four fixed source prefixes:
     `auto-recorded from session: <session-id> (<date>)` / `auto-recorded from file change: <path> (<date>)` / `auto-recorded from directory change: <dir> (<date>)` / `auto-recorded from Obsidian diary: <text>`.
     The second line is always `last updated: <UpdatedAt>` (given by the orchestrator; format `YYYY-MM-DD HH:MM`). Never invent the time or reuse an old value.
   - **When there is no substantive work**: output `NO_WORK` and write nothing.

## Times must be in the past (hard rule)

- Every task uses **real evidence times**: start = earliest, end = latest; `startDate` / `dueDate` / `completedTime` follow that window.
- **The end must not exceed `FallbackTime`** (the current moment, or 21:00 for a historical backfill). If it does, use `FallbackTime`. With no timestamp at all, use it for both ends.
- Writing a **future** time makes the task disappear from the completed list.

## Emoji table (reuse, do not invent)

| emoji | meaning |
|---|---|
| 🔬 | research / paper / writing / patent |
| 🧪 | experiment / simulation |
| 🔍 | characterization (SEM/XRD/Raman/contact angle…) |
| 📚 | literature / books / translation / references |
| 📅 | reports / weekly report / slides / Gantt |
| 💼 | job search (resume / application / assessment / recommendation) |
| 💰 | reimbursement / bills / invoices |
| 🛒 | purchasing / parcels / shipping |
| 🔧 | system & software maintenance / tooling |
| 📷 | media archiving (X/Weibo/images/video) |
| 📝 | notes and topic organization |
| 🍽️ | personal errands |
| 🎬 | movies |
| 📺 | series |

## Step 6: sync to the Obsidian diary

Use Read/Write to write **all of today's completed tasks** (including pre-existing ones) into the diary file passed by the orchestrator (`Diary file:` argument).

Copy this template exactly (the marker lines must not change, or idempotent replacement breaks):

```
<!-- dida365:begin (auto-generated) -->
## 滴答清单
> last updated: <UpdatedAt> (run <RunNumber>)
- <HH:MM–HH:MM> <task title 1>
- <HH:MM–HH:MM> <task title 2>
<!-- dida365:end -->
```

Rules:
- **Rewrite the `> last updated:` line every run** using the given `UpdatedAt` and `RunNumber`. Do not reuse old values or add other metadata lines.
- **Time prefix**: when both `startDate` and `completedTime` are timed, write `HH:MM–HH:MM ` (ASCII colon, en dash `–`). All-day or untimed legacy tasks: title only, never invent a time.
- Missing file → create it with just this block.
- Existing file with both markers → **replace only the content between them**; touch nothing outside.
- Existing file without markers → append a blank line and the block at the end.
- Ordering: **ascending by start time**; untimed tasks go **last**, ordered by the emoji order above, then title.
- Block content **must come from this run's `{{LIST_COMPLETED}}` result**; deleted tasks must not linger.
- Identical titles on the same day merge into one with ` ×N`, except tasks with `(n/N)` numbers (list them separately).
- Keep titles verbatim (including emoji).

## Step 7: reverse sync (Obsidian diary → task manager)

The user may have handwritten lines in today's diary that never became tasks. Fill the gaps.

1. Read today's diary (`Diary file`). **If missing, skip this step.**
2. Take **handwritten parts only**: exclude everything between `<!-- dida365:begin` and `<!-- dida365:end -->` (written by this pipeline; using it as input would self-increment). Also skip YAML frontmatter, `#` headings and blank lines.
3. Compare each line with today's task list fetched earlier (loose match: ignore emoji/punctuation/spaces; allow word-order changes; normalize Chinese numerals; ±2 days).
4. Decide "is this something that was done":
   - **Add**: concrete activities (experiment, writing, applying, simulation, errands, a visit, watching a film…).
   - **Do not add**: news commentary, other people's updates, pure opinions, names/nicknames, questions with no action.
   - Unsure → **do not add**.
5. Create like step 5: `add` then `update` with `status:2` + `completedTime`. Title `<emoji> <original text>`; content two lines — `auto-recorded from Obsidian diary: <text>` then `last updated: <UpdatedAt>`.

## Step 8: refresh the `last updated` timestamp

New tasks already carry it, but **pre-existing auto tasks** on that day still hold old values. Refresh all of them to this run's time:

1. Call `{{LIST_COMPLETED}}` once (00:00–23:59, `{{TIMEZONE}}`) for the **final task list**. This result also serves step 9; do not query again.
2. Only touch tasks whose content first line starts with one of the auto prefixes:
   `auto-recorded from session` / `auto-recorded from file change` / `auto-recorded from directory change` / `auto-recorded from Obsidian diary`.
   **Empty or user-written content is never touched.**
3. New content = strip any existing timestamp line (regex `(?:\r?\n)?last updated: \d{4}-\d{2}-\d{2} \d{2}:\d{2}\s*$`), then append `\nlast updated: <UpdatedAt>`. Skip if already current.
4. Call `{{UPDATE_TASKS}}`, ≤50 per batch, each item **only** `{id, projectId, content}` — never `status` / `completedTime` / `startDate` / `dueDate` / `title`.
5. A failure here is not fatal overall, but must be reported.

## Step 9: duplicate self-check (report only, never delete)

Using step 8's final list, compare every pair:

- **Directory first (before text similarity)**: if both contents carry paths (`auto-recorded from file change:` / `auto-recorded from directory change:`) and the paths differ → **not duplicates, do not print**. Same title, different folder = different work.
- Otherwise: after ignoring emoji/punctuation/spaces/numerals, if ≥72% of one title's character set is contained in the other → duplicate.
- **Guards**: ① different deliverable after removing the common part → not duplicate; ② title length difference >3 characters → not duplicate; ③ same title after removing `(n/N)` → intentional segments, do not print.
- **Never delete anything**, never rewrite titles because of a duplicate.
- For each duplicate pair, print a line before the final result: `DUP: <title A> || <title B>`.
- No duplicates → print nothing.

## Output

Print exactly one final line:
`DONE date=<date> created=<session records> fs=<file records> rev=<diary records> skipped=<skipped> dup=<duplicate pairs> stamp=<refreshed> mt=<manual timed> ext=<extended> diary=<ok|fail>`
or `NO_WORK`.

## Efficiency

- The evidence file can be long: skim `###` directory headings and counts first; do not read every line.
- At most **20** MCP tool calls total.
- Do not call `get_task_by_id` per task; do not query the same day twice.
- Finish within 8 minutes; the orchestrator will kill the run on timeout.
