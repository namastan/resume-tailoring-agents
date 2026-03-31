"""
mjr/builder.py
--------------
Converts one or more resume files into a structured mjr.yaml.

Run this once when setting up, or again when adding a new role.
The builder never overwrites existing coached_variants — it only
adds new experiences and bullets that aren't already in the MJR.

Usage:
    python mjr/builder.py --resume path/to/resume.pdf --output mjr.yaml

    # Multiple resumes (e.g. different versions):
    python mjr/builder.py --resume resume_v1.pdf resume_v2.pdf --output mjr.yaml

    # Append a new role to an existing MJR:
    python mjr/builder.py --resume new_resume.pdf --output mjr.yaml --merge
"""

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
import yaml
from dotenv import load_dotenv

load_dotenv()

# Resolve imports when running from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))
from mjr.schema import (
    Bullet,
    Education,
    Experience,
    MasterJobRepository,
    PersonalInfo,
    PM_SKILL_CATEGORIES,
)


# ---------------------------------------------------------------------------
# Resume text extraction
# ---------------------------------------------------------------------------

def extract_text_from_file(path: str) -> str:
    """
    Extract plain text from a resume file.
    Supports: .txt, .md, .pdf (via pypdf), .docx (via python-docx).
    """
    ext = Path(path).suffix.lower()

    if ext in (".txt", ".md"):
        return Path(path).read_text(encoding="utf-8")

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(path)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError:
            raise ImportError("Install pypdf to parse PDFs: pip install pypdf")

    if ext == ".docx":
        try:
            from docx import Document
            doc = Document(path)
            return "\n".join(p.text for p in doc.paragraphs)
        except ImportError:
            raise ImportError("Install python-docx to parse DOCX files: pip install python-docx")

    raise ValueError(f"Unsupported file type: {ext}. Use .txt, .pdf, or .docx.")


# ---------------------------------------------------------------------------
# LLM extraction prompt
# ---------------------------------------------------------------------------

EXTRACTION_PROMPT = """
You are a career data extraction expert. Analyze the resume text below and return
a structured JSON object representing the candidate's professional history.

CRITICAL RULES:
1. Extract ONLY information explicitly present in the resume text.
2. Do NOT invent, infer, or hallucinate any information.
3. Preserve exact metrics, numbers, and dates as written.
4. Each bullet point is a separate accomplishment — extract them individually.
5. Categorize each bullet into one or more of these 7 PM skill categories:
   {categories}

OUTPUT FORMAT (return only valid JSON, no markdown):
{{
  "personal": {{
    "name": "string",
    "email": "string or null",
    "phone": "string or null",
    "location": "string or null",
    "linkedin": "string or null",
    "github": "string or null"
  }},
  "experiences": [
    {{
      "company": "string",
      "title": "string",
      "start_date": "string (e.g. 2019-01)",
      "end_date": "string or null",
      "is_current": boolean,
      "description": "string or null",
      "bullets": [
        {{
          "original": "exact bullet text from resume",
          "categories": ["category_1", "category_2"]
        }}
      ]
    }}
  ],
  "skills": ["skill1", "skill2"],
  "education": [
    {{
      "institution": "string",
      "degree": "string",
      "field": "string",
      "graduation_year": integer or null
    }}
  ]
}}

RESUME TEXT:
{resume_text}
"""


def extract_mjr_from_text(resume_text: str, client: anthropic.Anthropic) -> dict:
    """Call Claude to extract structured MJR data from resume text."""
    prompt = EXTRACTION_PROMPT.format(
        categories=", ".join(PM_SKILL_CATEGORIES),
        resume_text=resume_text,
    )

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    return json.loads(raw)


# ---------------------------------------------------------------------------
# MJR construction
# ---------------------------------------------------------------------------

def build_mjr_from_extraction(data: dict) -> MasterJobRepository:
    """Convert raw LLM extraction output into a typed MasterJobRepository."""
    personal = PersonalInfo(**data["personal"])

    experiences = []
    for exp_data in data.get("experiences", []):
        bullets = [
            Bullet.new(
                original=b["original"],
                categories=b.get("categories", []),
            )
            for b in exp_data.get("bullets", [])
        ]
        experiences.append(Experience(
            company=exp_data["company"],
            title=exp_data["title"],
            start_date=exp_data["start_date"],
            end_date=exp_data.get("end_date"),
            is_current=exp_data.get("is_current", False),
            description=exp_data.get("description"),
            bullets=bullets,
        ))

    education = [Education(**e) for e in data.get("education", [])]

    return MasterJobRepository(
        personal=personal,
        experiences=experiences,
        skills=data.get("skills", []),
        education=education,
    )


def merge_into_existing(new_mjr: MasterJobRepository, existing_path: str) -> MasterJobRepository:
    """
    Merge a newly extracted MJR into an existing mjr.yaml.
    Existing coached_variants are preserved. New experiences are appended.
    Duplicate companies+titles are skipped.
    """
    existing = MasterJobRepository.from_yaml(existing_path)
    existing_keys = {(e.company, e.title) for e in existing.experiences}

    for exp in new_mjr.experiences:
        if (exp.company, exp.title) not in existing_keys:
            existing.experiences.append(exp)
            print(f"  Added: {exp.title} at {exp.company}")
        else:
            print(f"  Skipped (already exists): {exp.title} at {exp.company}")

    # Merge skills (deduplicated)
    existing.skills = list(set(existing.skills + new_mjr.skills))

    return existing


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build a Master Job Repository YAML from resume(s).")
    parser.add_argument("--resume", nargs="+", required=True, help="Path(s) to resume file(s)")
    parser.add_argument("--output", default="mjr.yaml", help="Output path for mjr.yaml (default: mjr.yaml)")
    parser.add_argument("--merge", action="store_true", help="Merge into existing MJR instead of overwriting")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable not set.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Combine all resume text
    combined_text = ""
    for resume_path in args.resume:
        print(f"Reading: {resume_path}")
        combined_text += extract_text_from_file(resume_path) + "\n\n"

    print("Extracting structured data from resume(s)...")
    raw_data = extract_mjr_from_text(combined_text, client)

    new_mjr = build_mjr_from_extraction(raw_data)

    if args.merge and Path(args.output).exists():
        print(f"Merging into existing MJR: {args.output}")
        mjr = merge_into_existing(new_mjr, args.output)
    else:
        mjr = new_mjr

    mjr.save(args.output)
    print(f"\nMJR saved to: {args.output}")
    print(f"  Experiences: {len(mjr.experiences)}")
    print(f"  Total bullets: {sum(len(e.bullets) for e in mjr.experiences)}")
    print(f"  Skills: {len(mjr.skills)}")


if __name__ == "__main__":
    main()
