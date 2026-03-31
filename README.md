# resume-tailoring-agents

A multi-component system for tailoring resumes to specific job descriptions using
a persistent career data structure and an interactive coaching agent.

Built and open-sourced by a Staff PM who needed this to actually work — not just
demo well.

---

## What This Is

Most AI resume tools rewrite your bullets for you. This system does something
different: it builds a structured record of your career (the **MJR**), analyzes
what a specific job actually requires, and uses an interactive coaching session
to help you surface evidence you already have but haven't articulated clearly.

The output is a tailored resume where every word came from you.

---

## How It Works

```
resume.pdf → [Builder] → mjr.yaml (your career, structured)
jd.txt     → [Analyst] → analysis.json (what this job actually needs)
                       → [Coach]    → coached bullets (saved back to mjr.yaml)
mjr.yaml + analysis   → [Pipeline] → tailored_resume.md
```

Three components, one persistent file:

**Builder** — parses your resume(s) into `mjr.yaml`. Run once.

**Job Analyst** — reads a job description, extracts non-generic must-haves,
scores your bullets, and identifies gaps. Run per application.

**Resume Coach** — an interactive CLI agent that runs a multi-turn Q&A on
weak bullets, produces improved versions, and saves them back to `mjr.yaml`
tagged by role type. The next time the analyst sees a similar role, it
automatically pulls the coached variant.

Full design rationale in [ARCHITECTURE.md](ARCHITECTURE.md) and [TRADEOFFS.md](TRADEOFFS.md).

---

## Quickstart

**1. Clone and install**

```bash
git clone https://github.com/namastan/resume-tailoring-agents.git
cd resume-tailoring-agents
pip install -r requirements.txt
```

**2. Add your API key**

```bash
cp .env.example .env
```

Open `.env` and add your Anthropic API key:
```
ANTHROPIC_API_KEY=sk-ant-...
```

You'll need an [Anthropic account](https://console.anthropic.com) to get a key.
API usage for a typical pipeline run costs roughly $0.01–0.05 depending on resume length.

**3. Try the example first (no resume needed)**

The `examples/` folder has a pre-built MJR and a sample job description so you
can see the full output before running it on your own data.

```bash
python pipeline.py \
  --jd examples/sample_jd.txt \
  --mjr examples/sample_mjr.yaml \
  --output examples/sample_output.md \
  --no-coach
```

Open `examples/sample_output.md` to see the tailored resume. Open
`analysis.json` to see the full job analysis — must-haves, bullet scores,
and gap identification.

**4. Run on your own resume**

```bash
# Step 1: Build your MJR from your resume (run once)
python mjr/builder.py --resume path/to/your_resume.pdf --output mjr.yaml

# Step 2: Run the full pipeline on a job description
python pipeline.py --jd path/to/job_description.txt --mjr mjr.yaml
```

Supported resume formats: `.pdf` (requires `pypdf`), `.docx` (requires
`python-docx`), `.txt`, `.md`.

The pipeline will score your bullets, optionally run an interactive coaching
session on weak ones, and produce a tailored resume markdown file.

---

## File Structure

```
resume-tailoring-agents/
├── mjr/
│   ├── builder.py          # Resume → mjr.yaml
│   ├── updater.py          # Writes coached variants back to MJR
│   └── schema.py           # MJR dataclasses and validation
│
├── agents/
│   ├── job_analyst.py      # JD → must-haves + bullet scoring
│   └── resume_coach.py     # Interactive multi-turn coaching loop
│
├── pipeline.py             # Orchestrator — runs the full flow
│
├── examples/
│   ├── sample_mjr.yaml     # Pre-populated example MJR
│   ├── sample_jd.txt       # Sample growth PM job description
│   └── sample_output.md    # What the pipeline produces
│
├── ARCHITECTURE.md         # System design and data flow
├── TRADEOFFS.md            # Key decisions and reasoning
├── requirements.txt
└── .env.example
```

---

## Requirements

- Python 3.10+
- `anthropic` SDK (Claude API key required)
- `pyyaml`
- Optional: `pypdf` (PDF resume parsing), `python-docx` (DOCX parsing)

---

## Key Design Decisions

**The MJR is a file, not a database.** Portable, version-controllable, readable
without tooling. The YAML file is the artifact — it gets richer over time as
coaching sessions accumulate.

**Original bullets are immutable.** The `original` field in `mjr.yaml` is never
modified. Coached improvements are stored as variants alongside the original,
tagged by role type.

**The coach doesn't invent content.** The multi-turn Q&A is designed to surface
evidence you already have. If you can't answer the coach's questions with real
specifics, the bullet won't get better — which is the correct behavior.

**Generic JD requirements are filtered before scoring.** "Strong communicator"
inflates scores without providing signal. The analyst filters these out so the
match score reflects differentiating requirements only.

Full reasoning in [TRADEOFFS.md](TRADEOFFS.md).

---

## What This Is Not

- Not a one-click resume generator
- Not a system that fabricates metrics or outcomes
- Not production-ready for a multi-user web app (see TRADEOFFS.md on the database question)
- Not a replacement for knowing your own career

---

## Background

This framework was extracted from [trajectorycareer.com](https://trajectorycareer.com),
a full-stack career optimization platform. The original system is a TypeScript/React/Express
application with authentication, Stripe payments, five resume templates, and a Postgres
database. This repo isolates the core agent logic — the parts that actually drive the
output quality — into a standalone Python framework anyone can fork and adapt.

The architectural decisions here reflect what worked (and what didn't) after building
and iterating on the full application. See [TRADEOFFS.md](TRADEOFFS.md) for the full account.

---

## License

MIT
