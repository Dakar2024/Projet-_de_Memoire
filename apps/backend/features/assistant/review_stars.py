"""ClinVar review status → stars, for the source cards.

Same table as `_REVIEW_STATUS_STARS` in src/transformations/silver_to_gold_analytique.py, which builds
`dim_review_status.stars` in the Gold layer. The backend runs in its own image and cannot import the
pipeline, so the table is copied here; test_review_stars.py fails if the two drift apart.
"""

REVIEW_STATUS_STARS: dict[str, int] = {
    "practice guideline": 4,
    "reviewed by expert panel": 3,
    "criteria provided, multiple submitters, no conflicts": 2,
    "criteria provided, single submitter": 1,
    "criteria provided, conflicting classifications": 1,
    "no assertion criteria provided": 0,
    "no assertion provided": 0,
    "no classification provided": 0,
    "no classification for the single variant": 0,
    "no classifications from unflagged records": 0,
}


def stars_for(review_status: str | None) -> int | None:
    """None when the status is missing or unknown, rather than a misleading zero."""
    if review_status is None:
        return None
    return REVIEW_STATUS_STARS.get(review_status.strip().lower())
