"""Parser 接口定义 — 将原始文件解析为结构化 ParsedDocument。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class Section:
    heading: str
    content: str
    page: int | None = None
    level: int = 1


@dataclass
class ParsedDocument:
    title: str
    sections: list[Section] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class DocumentParser(Protocol):
    supported_formats: list[str]

    async def parse(self, file_path: Path) -> ParsedDocument: ...
