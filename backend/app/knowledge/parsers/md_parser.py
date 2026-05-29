"""Markdown 解析器 — 按标题层级提取 Section。"""

from __future__ import annotations

import re
from pathlib import Path

from app.knowledge.parsers.interface import DocumentParser, ParsedDocument, Section


class MdParser:
    supported_formats = ["md", "markdown"]

    async def parse(self, file_path: Path) -> ParsedDocument:
        content = file_path.read_text(encoding="utf-8")
        title = file_path.stem

        title_match = re.match(r"^#\s+(.+)", content)
        if title_match:
            title = title_match.group(1).strip()

        sections: list[Section] = []
        raw_sections = re.split(r"\n(?=##\s)", content)

        for raw in raw_sections:
            raw = raw.strip()
            if not raw:
                continue
            heading_match = re.match(r"^#{1,3}\s+(.+)", raw)
            section_title = heading_match.group(1).strip() if heading_match else title
            level = len(heading_match.group(0).split()[0]) if heading_match else 1
            sections.append(Section(heading=section_title, content=raw, level=level))

        return ParsedDocument(
            title=title,
            sections=sections,
            metadata={"source_file": file_path.name},
        )
