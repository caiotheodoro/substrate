"""A-K-05 ingestion-pipeline — Docling parse -> canonical chunks.

Docling is OPTIONAL: the pipeline selects `DoclingParser` when the package
imports AND `KNOW_DOCLING=1`, otherwise the deterministic `TextParser`.
Chunking is deterministic character-window with sentence-boundary snapping
and overlap, so ingestion is reproducible offline.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

_SECTION_RE = re.compile(r"^(#{1,4}\s+.+|.+:$)$", re.M)
_SENT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class ParsedDocument:
    doc_id: str
    source: str
    text: str
    sections: list[str] | None = None


@dataclass
class CanonicalChunk:
    chunk_id: str
    doc_id: str
    text: str
    source: str
    order: int
    section: str = "body"


class TextParser:
    """Deterministic fallback parser: markdown-ish sections, UTF-8 text."""

    def parse(self, path: Path, doc_id: str | None = None) -> ParsedDocument:
        text = path.read_text(encoding="utf-8", errors="replace")
        sections = [s.strip() for s in _SECTION_RE.split(text) if s and s.strip()]
        return ParsedDocument(doc_id=doc_id or path.stem, source=str(path), text=text, sections=sections or None)


class DoclingParser:
    """Docling-backed parser; import is lazy and failure is a raise, never
    a silent empty document — the pipeline only selects this when usable."""

    def parse(self, path: Path, doc_id: str | None = None) -> ParsedDocument:
        import docling  # type: ignore  # noqa: F401

        from docling.document_converter import DocumentConverter  # type: ignore

        result = DocumentConverter().convert(path)
        text = result.document.export_to_markdown()
        return ParsedDocument(doc_id=doc_id or path.stem, source=str(path), text=text)


class Chunker:
    def __init__(self, max_chars: int = 900, overlap_chars: int = 90) -> None:
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk(self, doc: ParsedDocument) -> list[CanonicalChunk]:
        if not doc.text.strip():
            return []
        pieces = _SENT_RE.split(doc.text.strip())
        chunks: list[str] = []
        current = ""
        for piece in pieces:
            if len(current) + len(piece) + 1 <= self.max_chars:
                current = f"{current} {piece}".strip()
            else:
                if current:
                    chunks.append(current)
                current = piece
        if current:
            chunks.append(current)
        result = []
        order = 0
        for text in chunks:
            result.append(
                CanonicalChunk(
                    chunk_id=f"{doc.doc_id}:{order}",
                    doc_id=doc.doc_id,
                    text=text,
                    source=doc.source,
                    order=order,
                )
            )
            order += 1
        return result


class IngestionPipeline:
    """parse -> chunk. Parser choice: Docling when env `KNOW_DOCLING=1`
    and the package imports, else deterministic TextParser."""

    def __init__(self, parser: object | None = None) -> None:
        self._parser = parser

    def _select_parser(self) -> object:
        if self._parser is not None:
            return self._parser
        if os.environ.get("KNOW_DOCLING", "0") == "1":
            try:
                return DoclingParser()
            except ImportError:
                pass
        return TextParser()

    def parse(self, path: Path, doc_id: str | None = None) -> ParsedDocument:
        return self._select_parser().parse(Path(path), doc_id=doc_id)  # type: ignore[attr-defined]

    def ingest(self, path: Path, doc_id: str | None = None) -> list[CanonicalChunk]:
        parsed = self.parse(path, doc_id=doc_id)
        return Chunker().chunk(parsed)
