# Architecture

## System Overview

The resume tailoring system is built around a single persistent data structure —
the **Master Job Repository (MJR)** — that is read and written by three components:
a builder, an analyst, and a coach.

```
┌─────────────────────────────────────────────────────────────┐
│                    resume-tailoring-agents                   │
│                                                             │
│   resume.pdf                                                │
│       │                                                     │
│       ▼                                                     │
│  ┌──────────┐    writes    ┌─────────────┐                 │
│  │  Builder  │ ──────────▶ │  mjr.yaml   │ ◀── source of  │
│  └──────────┘              └─────────────┘     truth       │
│                                   │                         │
│                          reads    │    writes back          │
│                       ┌───────────┤◀──────────────┐        │
│                       │           │               │        │
│                       ▼           ▼               │        │
│   jd.txt ──▶  ┌─────────────┐  ┌───────────────┐ │        │
│               │ Job Analyst  │  │ Resume Coach  │─┘        │
│               └──────┬──────┘  └───────┬───────┘          │
│                      │                 │                    │
│               must_haves.json   coached_variants            │
│               analysis.json     (saved to MJR)             │
│                      │                 │                    │
│                      └────────┬────────┘                    │
│                               ▼                             │
│                    ┌────────────────────┐                   │
│                    │   pipeline.py      │                   │
│                    │  (orchestrator)    │                   │
│                    └────────┬───────────┘                   │
│                             │                               │
│                             ▼                               │
│                   tailored_resume.md                        │
└─────────────────────────────────────────────────────────────┘
```

---

## The MJR (Master Job Repository)

`mjr.yaml` is the central data structure. It is:

- **Written once** by `mjr/builder.py` from a resume file
- **Read** by both the job analyst and the resume coach
- **Updated incrementally** by the resume coach when coaching sessions produce improved bullets
- **Never fully overwritten** — coached variants accumulate alongside original bullets

### Key schema decisions

```
MasterJobRepository
├── personal (PersonalInfo)
├── experiences[]
│   ├── company, title, dates
│   └── bullets[]
│       ├── id          ← stable UUID, never changes
│       ├── original    ← exact text from resume, never modified
│       ├── categories  ← PM skill dimensions (set at extraction)
│       ├── strength_score ← set by job analyst per run
│       └── coached_variants[]
│           ├── role_type      ← auto-tagged by job analyst
│           ├── text           ← enhanced text from coaching session
│           ├── coaching_date
│           └── jd_source
├── skills[]
└── education[]
```

The separation between `original` (immutable) and `coached_variants` (accumulating)
is the core design decision. See [TRADEOFFS.md](TRADEOFFS.md) for the full reasoning.

---

## Component Responsibilities

### `mjr/builder.py` — Resume Parser

- Accepts `.txt`, `.pdf`, or `.docx` resume files
- Calls Claude to extract structured career data
- Outputs `mjr.yaml`
- Supports `--merge` flag to append new roles without overwriting existing variants
- Runs once per new resume (not per job application)

### `agents/job_analyst.py` — JD Analyzer

- Accepts a plain-text job description
- Extracts non-generic must-haves (filters out requirements every candidate meets)
- Auto-assigns a `role_type` from a fixed taxonomy
- Scores all MJR bullets against the must-haves
- Outputs `analysis.json` consumed by the coach and pipeline
- Reads MJR; does not write to it

### `agents/resume_coach.py` — Interactive Bullet Coach

- Reads `analysis.json` to identify weak bullets (score < 0.4)
- For each gap bullet, runs a multi-turn CLI conversation:
  1. Diagnoses what's weak about the bullet
  2. Asks 2-3 targeted questions to surface better evidence
  3. Produces an enhanced bullet using only evidence the user provides
  4. Asks for confirmation before saving
- Writes confirmed variants back to `mjr.yaml` via `mjr/updater.py`
- On future runs, checks for existing variants before re-coaching

### `pipeline.py` — Orchestrator

- Runs all three steps in sequence
- Prompts user before launching coaching (can be skipped with `--no-coach`)
- Generates final tailored resume markdown from MJR + analysis
- Saves output to a timestamped `.md` file

---

## Data Flow for a Typical Run

```
First time setup:
  resume.pdf → builder.py → mjr.yaml

Per job application:
  jd.txt + mjr.yaml → job_analyst.py → analysis.json
  analysis.json + mjr.yaml → resume_coach.py → mjr.yaml (updated)
  mjr.yaml + analysis.json → pipeline.py → tailored_resume.md
```

After the first setup, `mjr.yaml` gets richer over time. Each coaching session
adds a variant that is automatically reused when the analyst detects the same
role type in a future JD.

---

## Extending the System

**Swap the model:** The model is set per-function. Replace `claude-opus-4-5`
in any agent file with your preferred model. The `score_bullets` function in
`job_analyst.py` is the best candidate for a cheaper model (classification task).

**Add role types:** Extend `JD_ROLE_TYPES` in `mjr/schema.py`. Existing data
is unaffected.

**Add output formats:** Replace or extend the output step in `pipeline.py`. The
markdown output is intentionally simple — drop it into any resume builder or
template system.

**Add a database layer:** Replace `mjr.save()` / `MasterJobRepository.from_yaml()`
with your database read/write layer. The dataclass schema is the interface.
