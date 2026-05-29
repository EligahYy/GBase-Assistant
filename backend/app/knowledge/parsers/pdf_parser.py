"""PDF 解析器 — pdfplumber 逐页流式提取，避免全量页面驻留内存。"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

from app.knowledge.parsers.interface import DocumentParser, ParsedDocument, Section

logger = logging.getLogger(__name__)


class PdfParser:
    supported_formats = ["pdf"]

    def __init__(self, toc_path: str | None = None):
        self._toc_path = toc_path

    async def parse(self, file_path: Path) -> ParsedDocument:
        import pdfplumber

        toc_entries = self._load_toc(file_path)
        sections = await asyncio.to_thread(self._extract_with_toc, file_path, toc_entries)
        title = file_path.stem

        return ParsedDocument(
            title=title,
            sections=sections,
            metadata={
                "source_file": file_path.name,
                "page_count": sum(1 for s in sections if s.page is not None),
            },
        )

    def _load_toc(self, pdf_path: Path) -> list[dict]:
        """Try to load TOC JSON; return empty list if unavailable."""
        if self._toc_path and Path(self._toc_path).exists():
            import json
            with open(self._toc_path, encoding="utf-8") as f:
                return json.load(f)
        return []

    def _extract_with_toc(self, pdf_path: Path, toc_entries: list[dict]) -> list[Section]:
        import pdfplumber

        pdf = pdfplumber.open(str(pdf_path))
        total_pages = len(pdf.pages)

        try:
            if not toc_entries:
                return self._extract_flat(pdf, total_pages)
            return self._extract_by_toc(pdf, toc_entries, total_pages)
        finally:
            pdf.close()

    def _extract_flat(self, pdf, total_pages: int) -> list[Section]:
        """No TOC — each page becomes a Section."""
        sections: list[Section] = []
        for i in range(total_pages):
            page = pdf.pages[i]
            text = page.extract_text()
            if text and len(text.strip()) >= 50:
                text = self._clean_header_footer(text)
                sections.append(Section(heading=f"Page {i + 1}", content=text, page=i + 1))
        return sections

    def _extract_by_toc(self, pdf, toc_entries: list[dict], total_pages: int) -> list[Section]:
        """Use TOC to group pages into chapters."""
        sorted_toc = sorted(toc_entries, key=lambda e: e.get("page", 1))
        sections: list[Section] = []

        for i, entry in enumerate(sorted_toc):
            start_page = entry["page"]
            end_page = sorted_toc[i + 1]["page"] - 1 if i + 1 < len(sorted_toc) else total_pages
            end_page = max(end_page, start_page)

            text_parts: list[str] = []
            for p in range(start_page - 1, end_page):
                if p >= total_pages:
                    break
                page = pdf.pages[p]
                page_text = page.extract_text()
                if page_text:
                    page_text = self._clean_header_footer(page_text)
                    text_parts.append(page_text)

            content = "\n\n".join(text_parts)
            if len(content.strip()) >= 50:
                sections.append(Section(
                    heading=f"{entry.get('num', '')} {entry['title']}",
                    content=content,
                    page=start_page,
                ))

            if i % 50 == 0:
                logger.info("PDF sectioning: %d/%d", i + 1, len(sorted_toc))

        return sections

    @staticmethod
    def _clean_header_footer(text: str) -> str:
        text = re.sub(r"^GBase 8a MPP Cluster.*?\n", "", text)
        text = re.sub(r"文档版本953.*?南大通用数据技术股份有限公司.*?\n?$", "", text, flags=re.MULTILINE)
        return text.strip()
