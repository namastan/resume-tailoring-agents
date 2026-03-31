"""
agents/job_analyst.py
---------------------
Analyzes a job description and matches it against the user's MJR.

Two responsibilities:
  1. Extract non-generic must-haves from the JD (filtering out requirements
     that every candidate trivially meets, e.g. "strong communicator").
  2. Score and rank the user's bullets against those must-haves, and assign
     a role_type that the resume coach will use to tag coached variants.

The analyst reads from the MJR but never writes to it.

Usage:
    python agents/job_analyst.py --jd path/to/jd.txt --mjr mjr.yaml
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))
from mjr.schema import JD_ROLE_TYPES, MasterJobRepository


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

MUST_HAVE_EXTRACTION_PROMPT = """
You are an expert at reading job descriptions and identifying what actually
differentiates strong candidates from weak ones.

Your task: Extract the non-generic must-haves from this job description.

WHAT TO INCLUDE:
- Specific skills, domains, or technical areas explicitly mentioned
- Measurable experience requirements (e.g. "5+ years", "shipped 0-to-1 products")
- Domain knowledge that isn't universally expected (e.g. "healthcare data", "B2B SaaS")
- Leadership scope requirements (e.g. "managed cross-functional teams of 10+")
- Specific methodologies or tools that are clearly required (not just "nice to have")

WHAT TO EXCLUDE:
- Generic soft skills every candidate claims ("strong communicator", "team player")
- Obvious baseline requirements ("bachelor's degree", "proficiency in English")
- Vague aspirational language ("passionate about", "excited by")
- Requirements that appear in every PM job description

Also assign a role_type from this list that best describes this role:
{role_types}

OUTPUT FORMAT (valid JSON only, no markdown):
{{
  "role_type": "one of the role_types above",
  "role_summary": "2-sentence plain English summary of what this role actually does",
  "must_haves": [
    {{
      "requirement": "specific requirement text",
      "category": "one of: {pm_categories}",
      "weight": "high | medium | low"
    }}
  ]
}}

JOB DESCRIPTION:
{jd_text}
"""

BULLET_SCORING_PROMPT = """
You are evaluating how well a candidate's resume bullets match a set of job requirements.

For each bullet, assign:
- A relevance score (0.0 to 1.0) against the must-haves as a whole
- Which specific must-haves it addresses (by requirement text)

Be conservative. A bullet that only tangentially relates to a requirement should
score below 0.4. A bullet that directly addresses a must-have with a concrete
metric should score above 0.7.

OUTPUT FORMAT (valid JSON only):
{{
  "scored_bullets": [
    {{
      "bullet_id": "string",
      "original": "bullet text",
      "score": 0.0,
      "addresses": ["requirement text 1", "requirement text 2"]
    }}
  ]
}}

MUST-HAVES:
{must_haves}

BULLETS TO SCORE:
{bullets}
"""


# ---------------------------------------------------------------------------
# Analysis logic
# ---------------------------------------------------------------------------

def extract_must_haves(jd_text: str, client: anthropic.Anthropic) -> dict:
    from mjr.schema import PM_SKILL_CATEGORIES
    prompt = MUST_HAVE_EXTRACTION_PROMPT.format(
        role_types=", ".join(JD_ROLE_TYPES),
        pm_categories=", ".join(PM_SKILL_CATEGORIES),
        jd_text=jd_text,
    )
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def score_bullets(bullets: list[dict], must_haves: list[dict], client: anthropic.Anthropic) -> list[dict]:
    prompt = BULLET_SCORING_PROMPT.format(
        must_haves=json.dumps(must_haves, indent=2),
        bullets=json.dumps(bullets, indent=2),
    )
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    result = json.loads(raw.strip())
    return result["scored_bullets"]


def analyze(jd_path: str, mjr_path: str, client: anthropic.Anthropic) -> dict:
    """
    Full analyst run. Returns a structured analysis dict containing:
      - role_type (auto-assigned, used to tag coaching sessions)
      - role_summary
      - must_haves
      - scored_bullets (sorted by score descending)
      - gap_bullets (bullets scoring below 0.4, candidates for coaching)
      - overall_alignment_score
    """
    jd_text = Path(jd_path).read_text(encoding="utf-8")
    mjr = MasterJobRepository.from_yaml(mjr_path)

    print("Extracting must-haves from job description...")
    analysis = extract_must_haves(jd_text, client)
    role_type = analysis["role_type"]
    must_haves = analysis["must_haves"]

    # Flatten all bullets from MJR for scoring, checking for existing variants first
    bullet_inputs = []
    for company, bullet in mjr.all_bullets():
        # Check if a coached variant already exists for this role_type
        existing_variant = bullet.get_variant_for(role_type)
        text_to_score = existing_variant.text if existing_variant else bullet.original
        bullet_inputs.append({
            "bullet_id": bullet.id,
            "original": text_to_score,
            "has_coached_variant": existing_variant is not None,
            "company": company,
        })

    print(f"Scoring {len(bullet_inputs)} bullets against {len(must_haves)} must-haves...")
    scored = score_bullets(bullet_inputs, must_haves, client)

    # Sort by score descending
    scored.sort(key=lambda b: b["score"], reverse=True)

    # Identify gaps — bullets that are weak but could potentially be improved
    gap_bullets = [b for b in scored if b["score"] < 0.4]

    # Overall alignment: average of top-5 bullet scores
    top_scores = [b["score"] for b in scored[:5]]
    overall_score = sum(top_scores) / len(top_scores) if top_scores else 0.0

    return {
        "role_type": role_type,
        "role_summary": analysis["role_summary"],
        "must_haves": must_haves,
        "scored_bullets": scored,
        "gap_bullets": gap_bullets,
        "overall_alignment_score": round(overall_score, 2),
        "jd_source": Path(jd_path).name,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Analyze a JD against your MJR.")
    parser.add_argument("--jd", required=True, help="Path to job description text file")
    parser.add_argument("--mjr", default="mjr.yaml", help="Path to mjr.yaml")
    parser.add_argument("--output", default="analysis.json", help="Save analysis JSON to this path")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    result = analyze(args.jd, args.mjr, client)

    print(f"\n--- Job Analysis ---")
    print(f"Role type:         {result['role_type']}")
    print(f"Summary:           {result['role_summary']}")
    print(f"Must-haves found:  {len(result['must_haves'])}")
    print(f"Alignment score:   {result['overall_alignment_score']}")
    print(f"Bullets to coach:  {len(result['gap_bullets'])}")

    print("\nTop matching bullets:")
    for b in result["scored_bullets"][:5]:
        print(f"  [{b['score']:.2f}] {b['original'][:80]}...")

    # Save analysis for pipeline.py and resume_coach.py to consume
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nAnalysis saved to: {args.output}")


if __name__ == "__main__":
    main()
