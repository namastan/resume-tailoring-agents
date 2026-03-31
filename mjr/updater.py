"""
mjr/updater.py
--------------
Writes coached bullet variants back into mjr.yaml.

This module is called by the resume coach after a coaching session completes.
It is not intended to be run directly by users.

Design constraints:
  - bullet.original is never modified
  - If a variant with the same role_type already exists, it is replaced
  - All other bullets and experiences are untouched
"""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from mjr.schema import CoachedVariant, MasterJobRepository


def save_coached_variant(
    mjr_path: str,
    bullet_id: str,
    role_type: str,
    enhanced_text: str,
    jd_source: str = None,
) -> None:
    """
    Write a coached variant back to mjr.yaml.

    If a variant for the given role_type already exists on this bullet,
    it is replaced. This prevents duplicate variants for the same role type
    from accumulating across multiple coaching sessions.

    Args:
        mjr_path:      Path to the mjr.yaml file.
        bullet_id:     The stable ID of the bullet being updated.
        role_type:     JD role type assigned by the job analyst (e.g. 'growth-pm').
        enhanced_text: The coached bullet text produced by the resume coach.
        jd_source:     Optional filename or label of the JD that triggered coaching.
    """
    mjr = MasterJobRepository.from_yaml(mjr_path)

    bullet = mjr.get_bullet_by_id(bullet_id)
    if bullet is None:
        raise ValueError(f"Bullet ID '{bullet_id}' not found in MJR.")

    # Replace existing variant for this role_type, or append a new one
    existing_index = next(
        (i for i, v in enumerate(bullet.coached_variants) if v.role_type == role_type),
        None,
    )

    new_variant = CoachedVariant(
        role_type=role_type,
        text=enhanced_text,
        coaching_date=date.today().isoformat(),
        jd_source=jd_source,
    )

    if existing_index is not None:
        bullet.coached_variants[existing_index] = new_variant
    else:
        bullet.coached_variants.append(new_variant)

    mjr.save(mjr_path)
