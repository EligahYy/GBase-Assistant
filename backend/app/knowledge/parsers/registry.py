"""ParserRegistry — 根据文件类型查找对应的 Parser 实例。"""

from __future__ import annotations

from pathlib import Path

from app.knowledge.parsers.interface import DocumentParser
from app.knowledge.parsers.md_parser import MdParser
from app.knowledge.parsers.pdf_parser import PdfParser


class ParserRegistry:
    def __init__(self):
        self._parsers: dict[str, DocumentParser] = {}

    def register(self, parser: DocumentParser) -> None:
        for fmt in parser.supported_formats:
            self._parsers[fmt.lower()] = parser

    def get(self, file_type: str) -> DocumentParser | None:
        return self._parsers.get(file_type.lower())

    def supported_formats(self) -> list[str]:
        return list(self._parsers.keys())


def create_default_registry(pdf_toc_path: str | None = None) -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(MdParser())
    registry.register(PdfParser(toc_path=pdf_toc_path))
    return registry
