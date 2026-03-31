"""
pipeline.py
-----------
Orchestrates the full resume tailoring run end-to-end.

Steps:
  1. Job Analyst  — extract must-haves from JD, score MJR bullets
  2. Resume Coach — interactive coaching for gap bullets (optional)
  3. Output       — generate a tailored resume markdown file

Usage:
    # Full run with interactive coaching:
    python pipeline.py --jd path/to/jd.txt --mjr mjr.yaml

    # Skip coaching (output only):
    python pipeline.py --jd path/to/jd.txt --mjr mjr.yaml --no-coach

    # Specify output file:
    python pipeline.py --jd path/to/jd.txt --mjr mjr.yaml --output tailored_resume.md
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

import anthropic
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent))
from agents.job_analyst import analyze
from mjr.schema import MasterJobRepository


# ---------------------------------------------------------------------------
# Output generation
# ---------------------------------------------------------------------------

OUTPUT_PROMPT = """
You are generating a tailored resume for a product manager applying to a specific role.

INSTRUCTIONS:
1. Use ONLY bullets from the provided MJR. Do not invent content.
2. For each role, select the bullets most relevant to the job must-haves.
3. If a coached variant exists for the target role_type, use it instead of the original.
4. Order bullets within each role by relevance to must-haves (most relevant first).
5. Include all experiences — do not drop roles. Trim bullet count per role if needed.
6. Output clean markdown suitable for copy-paste into a resume document.

FORMAT:
# [Candidate Name]
[contact info on one line]

## Experience

### [Title] | [Company] | [Date range]
- Bullet 1
- Bullet 2

## Education
...

## Skills
...

---

MJR DATA:
{mjr_data}

ROLE TYPE: {role_type}
MUST-HAVES: {must_haves}
"""


def generate_tailored_resume(
    mjr: MasterJobRepository,
    analysis: dict,
    client: anthropic.Anthropic,
) -> str:
    role_type = analysis["role_type"]

    # Build MJR snapshot that includes coached variants for this role_type
    mjr_snapshot = {
        "personal": mjr.personal.__dict__,
        "experiences": [],
        "skills": mjr.skills,
        "education": [e.__dict__ for e in mjr.education],
    }

    for exp in mjr.experiences:
        exp_dict = {
            "company": exp.company,
            "title": exp.title,
            "start_date": exp.start_date,
            "end_date": exp.end_date,
            "is_current": exp.is_current,
            "bullets": [],
        }
        for bullet in exp.bullets:
            variant = bullet.get_variant_for(role_type)
            exp_dict["bullets"].append({
                "id": bullet.id,
                "text": variant.text if variant else bullet.original,
                "is_coached": variant is not None,
                "categories": bullet.categories,
            })
        mjr_snapshot["experiences"].append(exp_dict)

    prompt = OUTPUT_PROMPT.format(
        mjr_data=json.dumps(mjr_snapshot, indent=2),
        role_type=role_type,
        must_haves=json.dumps(analysis["must_haves"], indent=2),
    )

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    return message.content[0].text.strip()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run the full resume tailoring pipeline.")
    parser.add_argument("--jd", required=True, help="Path to job description text file")
    parser.add_argument("--mjr", default="mjr.yaml", help="Path to mjr.yaml")
    parser.add_argument("--output", default=None, help="Output markdown file path")
    parser.add_argument("--no-coach", action="store_true", help="Skip interactive coaching")
    parser.add_argument("--analysis-output", default="analysis.json", help="Save analysis JSON")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # -------------------------------------------------------------------
    # Step 1: Job Analyst
    # -------------------------------------------------------------------
    print("\n[1/3] Running job analyst...")
    analysis = analyze(args.jd, args.mjr, client)

    with open(args.analysis_output, "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"\nRole type:        {analysis['role_type']}")
    print(f"Alignment score:  {analysis['overall_alignment_score']}")
    print(f"Must-haves:       {len(analysis['must_haves'])}")
    print(f"Gap bullets:      {len(analysis['gap_bullets'])}")

    # -------------------------------------------------------------------
    # Step 2: Resume Coach (optional, interactive)
    # -------------------------------------------------------------------
    if not args.no_coach and analysis["gap_bullets"]:
        print(f"\n[2/3] {len(analysis['gap_bullets'])} bullets could be strengthened.")
        run_coaching = input("Run interactive coaching session? (y/n): ").strip().lower()

        if run_coaching == "y":
            from agents.resume_coach import run_coaching_session
            mjr = MasterJobRepository.from_yaml(args.mjr)

            for i, gap in enumerate(analysis["gap_bullets"], 1):
                bullet = mjr.get_bullet_by_id(gap["bullet_id"])
                if not bullet:
                    continue
                print(f"\nBullet {i} of {len(analysis['gap_bullets'])}")
                run_coaching_session(
                    bullet_id=bullet.id,
                    original_text=bullet.original,
                    role_type=analysis["role_type"],
                    must_haves=analysis["must_haves"],
                    mjr_path=args.mjr,
                    jd_source=analysis.get("jd_source", "unknown"),
                    client=client,
                )
                if i < len(analysis["gap_bullets"]):
                    cont = input("\nNext bullet? (y/n): ").strip().lower()
                    if cont != "y":
                        break
    else:
        print("\n[2/3] Skipping coaching.")

    # -------------------------------------------------------------------
    # Step 3: Generate tailored resume output
    # -------------------------------------------------------------------
    print("\n[3/3] Generating tailored resume...")
    mjr = MasterJobRepository.from_yaml(args.mjr)
    tailored = generate_tailored_resume(mjr, analysis, client)

    # Determine output path
    if args.output:
        out_path = args.output
    else:
        jd_stem = Path(args.jd).stem
        out_path = f"tailored_resume_{jd_stem}_{date.today().isoformat()}.md"

    Path(out_path).write_text(tailored, encoding="utf-8")

    print(f"\nTailored resume saved to: {out_path}")
    print(f"Analysis saved to:        {args.analysis_output}")
    print("\nDone.")


if __name__ == "__main__":
    main()
