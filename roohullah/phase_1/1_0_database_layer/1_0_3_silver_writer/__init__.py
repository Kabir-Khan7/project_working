"""Silver Writer module — transforms bronze rows into normalised silver transactions."""

try:
    from .silver_writer import (
        SilverWriter,
        ProcessResult,
        parse_date,
        parse_amount,
        detect_language,
        mask_pii,
        compute_fiscal_year,
        compute_quality_score,
    )
except ImportError:
    # When running as a script or pytest collects this file directly
    from silver_writer import (  # type: ignore[no-redef]
        SilverWriter,
        ProcessResult,
        parse_date,
        parse_amount,
        detect_language,
        mask_pii,
        compute_fiscal_year,
        compute_quality_score,
    )

__all__ = [
    "SilverWriter",
    "ProcessResult",
    "parse_date",
    "parse_amount",
    "detect_language",
    "mask_pii",
    "compute_fiscal_year",
    "compute_quality_score",
]
