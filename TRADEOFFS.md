# Design Tradeoffs

This document explains the key decisions behind the resume tailoring agent system —
what was considered, what was chosen, and why. It is intended to be useful both for
contributors extending the framework and for readers evaluating the design approach.

---

## 1. The MJR is a file, not a database

The Master Job Repository (MJR) is stored as a local YAML file rather than a
database or API-backed service.

**What was considered:** A Postgres schema (normalized tables for roles, bullets,
and variants) offers better query performance, referential integrity, and
multi-user support.

**What was chosen and why:** A flat YAML file is readable without tooling, portable
across machines, version-controllable with Git, and requires zero infrastructure
to run. For a single user's career history, the scale doesn't justify the
operational overhead of a database. The YAML structure is still strongly typed via
Python dataclasses — the file is just the serialization format.

**The tradeoff:** Multi-user support would require a proper database layer. The
current design is explicitly single-user. Anyone extending this to a web app should
replace the YAML layer with a database while keeping the schema and agent logic intact.

---

## 2. `bullet.original` is immutable

Once a bullet is extracted from a resume and written to the MJR, its `original`
field is never modified — even when the coach produces a better version.

**What was considered:** Overwriting the original with the coached variant is
simpler (one field per bullet) and keeps the file cleaner.

**What was chosen and why:** The original text is the ground truth. It preserves
the candidate's exact words in case the coached variant is rejected, over-tuned,
or inappropriate for a different role type. The `coached_variants` array exists
precisely so improvements accumulate alongside the original rather than replacing it.

**The tradeoff:** The YAML file grows over time as variants accumulate. This is
intentional — the growing history of variants is what makes the system more useful
the longer it's used.

---

## 3. Coached variants are tagged by role type, not by job title

When the resume coach saves an enhanced bullet, it tags it with a `role_type`
(e.g., `growth-pm`, `platform-pm`) rather than with a specific job title or
company name.

**What was considered:** Tagging by specific job title (e.g., "Senior PM, Acme
Growth Team") is more precise. Free-form tags chosen by the user are more flexible.

**What was chosen and why:** Role-type tagging is auto-assigned by the job analyst
based on JD analysis, requiring no user input. More importantly, the same coached
variant is often reusable across multiple applications to similar roles. A
`growth-pm` variant written for one role will be surfaced automatically the next
time the analyst detects a `growth-pm` role — without requiring a new coaching session.

**The tradeoff:** The role type taxonomy (`JD_ROLE_TYPES` in `mjr/schema.py`) is
opinionated and limited. Roles that span multiple categories (e.g., a hybrid
strategy/growth role) will be assigned a single type, which may not perfectly
match. The list can be extended without breaking existing data.

---

## 4. The coach reorders and sharpens bullets — it does not rewrite them

The resume coach is constrained to surface evidence that already exists in the
user's experience. It cannot add metrics, outcomes, or facts that the user
doesn't provide during the coaching session.

**What was considered:** Allowing the LLM to rewrite bullets freely (adding plausible
metrics, strengthening verbs, reframing scope) produces more impressive-sounding
output with less user effort.

**What was chosen and why:** Fabricated metrics are a credibility risk. If a
candidate can't speak to a number in an interview, the resume has done more harm
than good. The coaching loop (multi-turn Q&A) is designed to surface what the
candidate actually did but didn't articulate clearly — not to invent a better story.

**The tradeoff:** The coaching session requires user effort. The Q&A loop takes
5-10 minutes per bullet. Users who want one-click improvement will find this
frustrating. That friction is intentional.

---

## 5. Generic JD requirements are filtered before scoring

The job analyst explicitly removes requirements that appear in nearly every PM
job description before scoring bullets against must-haves.

**What was considered:** Scoring against all stated requirements, including soft
skills and baseline expectations.

**What was chosen and why:** Without filtering, match scores are artificially
inflated. If "excellent communication skills" counts as a must-have, almost every
PM candidate matches it — making the score meaningless as a signal. The analyst
prompt is explicit about what to exclude: universal soft skills, obvious baseline
requirements, and vague aspirational language. The score only reflects
differentiating requirements.

**The tradeoff:** The filtering is done by the LLM, which means it can occasionally
remove a requirement that was genuinely specific to the role. The `must_haves`
field in `analysis.json` is human-readable — reviewing it before a coaching session
takes less than a minute.

---

## 6. The pipeline uses one model throughout

The system uses Claude throughout (extraction, analysis, coaching, output generation)
rather than mixing providers.

**What was considered:** The original application this was extracted from used
Claude for extraction and generation, and GPT-4o-mini for scoring and classification.
The mixed approach reduces cost because classification tasks don't require the
stronger model.

**What was chosen and why:** Single-provider simplicity — one API key, one billing
account, one failure surface. For an open-source framework, reducing setup friction
matters more than cost optimization. The cost savings from using a cheaper model
for scoring are real but modest at single-user scale.

**The tradeoff:** Anyone running this at scale (many users, many JDs per day) should
revisit the dual-model approach. The `score_bullets` function in `agents/job_analyst.py`
is the natural swap point — it can be replaced with a GPT-4o-mini call without
touching the rest of the system.
