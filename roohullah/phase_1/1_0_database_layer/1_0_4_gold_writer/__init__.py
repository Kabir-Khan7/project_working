"""Gold Writer module — promotes silver rows to enriched gold transactions."""

try:
    from .gold_writer import (
        GoldWriter,
        PeriodSummaryBuilder,
        PromotionResult,
        build_embedding_text,
        classify_fbr,
        format_amount,
        format_date_human,
    )
except ImportError:
    # When running as a script or pytest collects this file directly
    from gold_writer import (  # type: ignore[no-redef]
        GoldWriter,
        PeriodSummaryBuilder,
        PromotionResult,
        build_embedding_text,
        classify_fbr,
        format_amount,
        format_date_human,
    )

__all__ = [
    "GoldWriter",
    "PeriodSummaryBuilder",
    "PromotionResult",
    "build_embedding_text",
    "classify_fbr",
    "format_amount",
    "format_date_human",
]
