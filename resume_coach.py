"""
agents/resume_coach.py
----------------------
An interactive coaching agent that helps improve weak resume bullets.

The coach runs a multi-turn CLI conversation for each underperforming bullet,
asking targeted questions to surface evidence the user hasn't made explicit.
It then produces an enhanced bullet — reworded to surface that evidence more
clearly — and writes the result back to mjr.yaml via the updater.

Design constraints:
  - The bullet's factual content is never invented. The coach only helps
    surface what the user already did but didn't articulate well.
  - If a coached variant already exists in the MJR for this role_type,
    the coach shows it and asks whether to re-coach or skip.
  - coached_variants accumulate in the MJR across sessions. They are
    tagged by role_type (auto-assigned by the job analyst) so future
    pipeline runs can retrieve the right variant without user input.

Usage:
    # Coach all gap bullets from an analysis run:
    python agents/resume_coach.py --analysis analysis.json --mjr mjr.yaml

    # Coach a specific bullet by ID:
    python agents/resume_coach.py --bullet-id abc12345 --role-type growth-pm --mjr mjr.yaml
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
from mjr.schema import MasterJobRepository
from mjr.updater import save_coached_variant


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

ASSESS_BULLET_PROMPT = """
You are a resume coach helping a product manager strengthen a weak resume bullet.

The bullet below scored low against the job requirements. Your job is to identify
specifically what's missing or unclear — not to rewrite it, but to generate
targeted questions that will help the candidate surface better evidence.

Generate 2-3 focused questions. Each question should target one of:
  - Missing metrics (what was the actual impact, in numbers?)
  - Missing context (how large was the scope, team, or system?)
  - Missing causality (what specifically did YOU do to drive the result?)
  - Missing relevance (how does this connect to what the role actually needs?)

Do not ask generic questions like "Can you tell me more?" or "What was your role?".
Be specific to the bullet content.

OUTPUT FORMAT (valid JSON only):
{{
  "weakness": "1-2 sentence diagnosis of what's missing from this bullet",
  "questions": [
    "Specific question 1?",
    "Specific question 2?",
    "Specific question 3?"
  ]
}}

BULLET:
{bullet_text}

JOB MUST-HAVES (for context):
{must_haves}
"""

ENHANCE_BULLET_PROMPT = """
You are a resume coach helping a product manager rewrite a weak bullet using
additional context they've just provided.

CONSTRAINTS:
1. Do not invent facts, metrics, or outcomes not present in the original bullet
   or the candidate's answers.
2. Preserve the core claim — only clarify and sharpen it.
3. Use the PCA format: [Action Verb] + [Context/Scope] + [Result] + [Metric].
4. The enhanced bullet should be 1-2 sentences maximum.
5. Do not use filler phrases like "successfully", "effectively", or "leveraged".

OUTPUT FORMAT (valid JSON only):
{{
  "enhanced_bullet": "The improved bullet text",
  "changes_made": "Brief explanation of what was changed and why"
}}

ORIGINAL BULLET:
{original}

CANDIDATE'S ANSWERS:
{answers}

JOB MUST-HAVES (for alignment context):
{must_haves}
"""


# ---------------------------------------------------------------------------
# Coaching session
# ---------------------------------------------------------------------------

def assess_bullet(bullet_text: str, must_haves: list[dict], client: anthropic.Anthropic) -> dict:
    prompt = ASSESS_BULLET_PROMPT.format(
        bullet_text=bullet_text,
        must_haves=json.dumps(must_haves, indent=2),
    )
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def enhance_bullet(
    original: str,
    answers: list[dict],
    must_haves: list[dict],
    client: anthropic.Anthropic,
) -> dict:
    answers_text = "\n".join(f"Q: {a['question']}\nA: {a['answer']}" for a in answers)
    prompt = ENHANCE_BULLET_PROMPT.format(
        original=original,
        answers=answers_text,
        must_haves=json.dumps(must_haves, indent=2),
    )
    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw.strip())


def run_coaching_session(
    bullet_id: str,
    original_text: str,
    role_type: str,
    must_haves: list[dict],
    mjr_path: str,
    jd_source: str,
    client: anthropic.Anthropic,
) -> str:
    """
    Run an interactive CLI coaching session for one bullet.
    Returns the enhanced bullet text, and saves it to the MJR.
    """
    print("\n" + "=" * 60)
    print("BULLET TO IMPROVE:")
    print(f"  {original_text}")
    print("=" * 60)

    # Assess the bullet and generate questions
    print("\nAnalyzing bullet weaknesses...")
    assessment = assess_bullet(original_text, must_haves, client)

    print(f"\nDiagnosis: {assessment['weakness']}")
    print("\nI have a few questions to help sharpen this bullet.")
    print("Answer as specifically as you can. Type 'skip' to skip a question.\n")

    answers = []
    for i, question in enumerate(assessment["questions"], 1):
        print(f"Q{i}: {question}")
        answer = input("    Your answer: ").strip()
        if answer.lower() != "skip":
            answers.append({"question": question, "answer": answer})
        print()

    if not answers:
        print("No answers provided. Skipping this bullet.")
        return original_text

    # Generate enhanced bullet
    print("Enhancing bullet based on your answers...")
    result = enhance_bullet(original_text, answers, must_haves, client)

    enhanced = result["enhanced_bullet"]

    print("\n" + "-" * 60)
    print("ORIGINAL:  ", original_text)
    print("ENHANCED:  ", enhanced)
    print("CHANGES:   ", result["changes_made"])
    print("-" * 60)

    confirm = input("\nSave this to your MJR? (y/n): ").strip().lower()
    if confirm == "y":
        save_coached_variant(
            mjr_path=mjr_path,
            bullet_id=bullet_id,
            role_type=role_type,
            enhanced_text=enhanced,
            jd_source=jd_source,
        )
        print(f"Saved to MJR under role_type '{role_type}'.")
    else:
        print("Discarded. Original bullet unchanged in MJR.")

    return enhanced


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Interactively coach weak resume bullets.")
    parser.add_argument("--analysis", help="Path to analysis.json from job_analyst.py")
    parser.add_argument("--bullet-id", help="Coach a specific bullet by ID")
    parser.add_argument("--role-type", help="Role type (required if using --bullet-id)")
    parser.add_argument("--mjr", default="mjr.yaml", help="Path to mjr.yaml")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    mjr = MasterJobRepository.from_yaml(args.mjr)

    # --- Mode 1: Coach all gap bullets from an analysis run ---
    if args.analysis:
        with open(args.analysis) as f:
            analysis = json.load(f)

        role_type = analysis["role_type"]
        must_haves = analysis["must_haves"]
        jd_source = analysis.get("jd_source", "unknown")
        gap_bullets = analysis["gap_bullets"]

        if not gap_bullets:
            print("No gap bullets identified. Your MJR aligns well with this role.")
            return

        print(f"\nRole type: {role_type}")
        print(f"Gap bullets to coach: {len(gap_bullets)}")
        print("\nFor each bullet, I'll ask 2-3 questions to help surface better evidence.")
        print("Type 'skip' to skip a question, or Ctrl+C to exit at any time.\n")

        for i, gap in enumerate(gap_bullets, 1):
            bullet = mjr.get_bullet_by_id(gap["bullet_id"])
            if not bullet:
                continue

            # Check for existing coached variant
            existing = bullet.get_variant_for(role_type)
            if existing:
                print(f"\n[{i}/{len(gap_bullets)}] Existing coached variant found for '{role_type}':")
                print(f"  {existing.text}")
                recoach = input("  Re-coach this bullet? (y/n): ").strip().lower()
                if recoach != "y":
                    continue

            print(f"\n[{i}/{len(gap_bullets)}] Score: {gap['score']:.2f}")
            run_coaching_session(
                bullet_id=bullet.id,
                original_text=bullet.original,
                role_type=role_type,
                must_haves=must_haves,
                mjr_path=args.mjr,
                jd_source=jd_source,
                client=client,
            )

            if i < len(gap_bullets):
                cont = input("\nContinue to next bullet? (y/n): ").strip().lower()
                if cont != "y":
                    break

    # --- Mode 2: Coach a specific bullet by ID ---
    elif args.bullet_id:
        if not args.role_type:
            print("Error: --role-type is required when using --bullet-id.")
            sys.exit(1)

        bullet = mjr.get_bullet_by_id(args.bullet_id)
        if not bullet:
            print(f"Error: Bullet ID '{args.bullet_id}' not found in MJR.")
            sys.exit(1)

        run_coaching_session(
            bullet_id=bullet.id,
            original_text=bullet.original,
            role_type=args.role_type,
            must_haves=[],
            mjr_path=args.mjr,
            jd_source="manual",
            client=client,
        )

    else:
        print("Error: Provide either --analysis or --bullet-id.")
        parser.print_help()
        sys.exit(1)

    print("\nCoaching session complete. MJR updated.")


if __name__ == "__main__":
    main()
