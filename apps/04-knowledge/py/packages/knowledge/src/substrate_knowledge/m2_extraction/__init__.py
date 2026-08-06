"""M2 — extraction: ingestion, typed extraction, evals, telemetry."""

from substrate_knowledge.m2_extraction.extractor import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
    InstructorExtractor,
    PatternExtractor,
)
from substrate_knowledge.m2_extraction.ingest import (
    CanonicalChunk,
    Chunker,
    DoclingParser,
    IngestionPipeline,
    ParsedDocument,
    TextParser,
)

__all__ = [
    "CanonicalChunk",
    "Chunker",
    "DoclingParser",
    "IngestionPipeline",
    "ParsedDocument",
    "TextParser",
    "ExtractedEntity",
    "ExtractedRelation",
    "ExtractionResult",
    "InstructorExtractor",
    "PatternExtractor",
]
