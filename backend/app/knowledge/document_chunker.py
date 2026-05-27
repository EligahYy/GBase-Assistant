"""官方 PDF 产品手册章节切片器 + Qdrant 索引。

将 GBase 8a 官方 PDF 手册按章节目录切分为独立文档块，
嵌入 Qdrant knowledge 集合，替换旧的模型生成内容。

用法:
  .venv/bin/python -m app.knowledge.document_chunker --pdf path/to/manual.pdf --toc path/to/toc.json
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════

@dataclass
class TOCEntry:
    num: str          # "4.8.2"
    title: str        # "语法格式"
    page: int         # PDF 页码 (1-based)
    depth: int        # 层级深度

@dataclass
class DocumentChunk:
    chapter_num: str
    chapter_title: str
    page_start: int
    page_end: int
    content: str
    metadata: dict = field(default_factory=dict)

    def to_embedding_text(self) -> str:
        """生成用于向量嵌入的文本。"""
        parts = [
            f"章节: {self.chapter_num} {self.chapter_title}",
            f"来源: {self.metadata.get('source', 'GBase 8a 产品手册')}",
            f"页码范围: {self.page_start}-{self.page_end}",
            "",
            self.content,
        ]
        return "\n".join(parts)

    def to_qdrant_payload(self) -> dict:
        return {
            "chapter_num": self.chapter_num,
            "chapter_title": self.chapter_title,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "source": self.metadata.get("source", "GBase 8a 产品手册"),
            "version": self.metadata.get("version", "V9.5.3"),
            "content": self.content[:2000],  # 截断存储，完整内容在嵌入文本中
        }


# ═══════════════════════════════════════════════════════════════════
# TOC Parser
# ═══════════════════════════════════════════════════════════════════

def parse_toc(toc_json_path: str | Path) -> list[TOCEntry]:
    """从 JSON 文件加载章节目录。"""
    with open(toc_json_path, encoding="utf-8") as f:
        data = json.load(f)

    entries = []
    for item in data:
        entries.append(TOCEntry(
            num=item["num"],
            title=item["title"],
            page=item["page"],
            depth=item["depth"],
        ))
    return entries


# ═══════════════════════════════════════════════════════════════════
# PDF Chapter Slicer
# ═══════════════════════════════════════════════════════════════════

class PDFChapterSlicer:
    """按章节目录将 PDF 切分为文档块。"""

    def __init__(self, pdf_path: str | Path, toc_entries: list[TOCEntry]):
        self.pdf_path = Path(pdf_path)
        self.toc = sorted(toc_entries, key=lambda e: e.page)

    def slice(self) -> list[DocumentChunk]:
        """切分 PDF，返回文档块列表。"""
        logger.info("Opening PDF: %s", self.pdf_path)
        pdf = pdfplumber.open(str(self.pdf_path))
        total_pages = len(pdf.pages)

        chunks = []
        for i, entry in enumerate(self.toc):
            start_page = entry.page

            # 确定结束页：下一个章节的起始页 - 1，或 PDF 末尾
            if i + 1 < len(self.toc):
                end_page = self.toc[i + 1].page - 1
                if end_page < start_page:
                    end_page = start_page
            else:
                end_page = total_pages

            # 提取页面文本
            text_parts = []
            for p in range(start_page - 1, min(end_page, total_pages)):
                page_text = pdf.pages[p].extract_text()
                if page_text:
                    # 去除页眉 "GBase 8a MPP Cluster产品手册..."
                    page_text = re.sub(
                        r'^GBase 8a MPP Cluster.*?\n',
                        '', page_text
                    )
                    # 去除页脚 "文档版本953..."
                    page_text = re.sub(
                        r'文档版本953.*?南大通用数据技术股份有限公司.*?\n?$',
                        '', page_text, flags=re.MULTILINE
                    )
                    text_parts.append(page_text.strip())

            content = "\n\n".join(text_parts)
            if not content.strip():
                continue

            # 构建父级标题路径
            parent_path = self._build_parent_path(entry)

            # 大章节子分片：超过阈值时按子标题或固定大小切分
            sub_chunks = self._split_large_chapter(
                content, entry, parent_path, start_page, end_page
            )
            chunks.extend(sub_chunks)

        pdf.close()
        logger.info("Sliced %d chapters from %d pages (%d chunks)",
                     len(self.toc), total_pages, len(chunks))
        return chunks

    def _split_large_chapter(
        self, content: str, entry: TOCEntry, parent_path: str,
        start_page: int, end_page: int,
    ) -> list[DocumentChunk]:
        """大章节子分片：按子标题切分，或固定大小切分。"""
        MAX_CHUNK_SIZE = 5000   # 超过此字符数则子分片
        CHUNK_OVERLAP = 500     # 相邻 chunk 重叠字符数

        if len(content) <= MAX_CHUNK_SIZE:
            return [DocumentChunk(
                chapter_num=entry.num,
                chapter_title=f"{parent_path}{entry.title}" if parent_path else entry.title,
                page_start=start_page,
                page_end=end_page,
                content=content,
                metadata={
                    "source": "GBase 8a MPP Cluster产品手册",
                    "version": "V9.5.3",
                    "depth": entry.depth,
                    "parent_path": parent_path,
                },
            )]

        # 尝试按子标题切分（匹配 "5.1.5.1 函数名" 或 "函数名()" 等模式）
        sub_headings = list(re.finditer(
            r'(?:^|\n)\s*((?:\d+\.?){1,4}\s+[^\n]{2,80}|[A-Z_]+\s*\([^)]*\)[^\n]{0,60}|[#＃]\s+[^\n]{2,80})\n',
            content, re.MULTILINE
        ))

        if len(sub_headings) >= 2:
            # 按子标题边界切分
            chunks = []
            for i, m in enumerate(sub_headings):
                chunk_start = m.start()
                chunk_end = sub_headings[i + 1].start() if i + 1 < len(sub_headings) else len(content)
                chunk_content = content[chunk_start:chunk_end].strip()
                if len(chunk_content) < 50:
                    continue

                sub_title = m.group(1).strip()
                chunks.append(DocumentChunk(
                    chapter_num=entry.num,
                    chapter_title=f"{parent_path}{entry.title} > {sub_title}",
                    page_start=start_page,
                    page_end=end_page,
                    content=chunk_content,
                    metadata={
                        "source": "GBase 8a MPP Cluster产品手册",
                        "version": "V9.5.3",
                        "depth": entry.depth + 1,
                        "parent_path": f"{parent_path}{entry.title}",
                    },
                ))
            if chunks:
                logger.debug("Split %s into %d sub-chunks by headings", entry.num, len(chunks))
                return chunks

        # 回退：固定大小切分
        chunks = []
        pos = 0
        part = 0
        while pos < len(content):
            chunk_end = min(pos + MAX_CHUNK_SIZE, len(content))
            chunk_content = content[pos:chunk_end]
            chunks.append(DocumentChunk(
                chapter_num=entry.num,
                chapter_title=f"{parent_path}{entry.title} (第{part + 1}部分)",
                page_start=start_page,
                page_end=end_page,
                content=chunk_content,
                metadata={
                    "source": "GBase 8a MPP Cluster产品手册",
                    "version": "V9.5.3",
                    "depth": entry.depth + 1,
                    "parent_path": f"{parent_path}{entry.title}",
                    "sub_part": part + 1,
                },
            ))
            pos = chunk_end - CHUNK_OVERLAP
            part += 1

        logger.debug("Split %s into %d fixed-size sub-chunks", entry.num, len(chunks))
        return chunks

    def _build_parent_path(self, entry: TOCEntry) -> str:
        """构建父级标题路径，如 '4 管理员指南 > 4.8 备份恢复管理 > '"""
        if entry.depth == 0:
            return ""

        parts = entry.num.split('.')
        parents = []
        for i in range(1, len(parts)):
            parent_num = '.'.join(parts[:i])
            # 查找父章节
            for e in self.toc:
                if e.num == parent_num:
                    parents.append(e.title)
                    break

        return ' > '.join(parents) + ' > ' if parents else ''


# ═══════════════════════════════════════════════════════════════════
# Qdrant Indexer
# ═══════════════════════════════════════════════════════════════════

class QdrantKnowledgeIndexer:
    """将文档块索引到 Qdrant knowledge 集合。"""

    COLLECTION_NAME = "knowledge"

    def __init__(self, embedder=None):
        self._embedder = embedder

    async def index_chunks(
        self,
        chunks: list[DocumentChunk],
        clear_existing: bool = True,
    ) -> int:
        """将文档块嵌入并索引到 Qdrant。

        Args:
            chunks: 文档块列表
            clear_existing: 是否先清空旧数据

        Returns:
            索引的文档块数量
        """
        from app.vector.client import get_qdrant_manager
        from app.vector.embedder import get_embedder

        embedder = self._embedder or get_embedder()
        qdrant = get_qdrant_manager()

        # 确保集合存在
        await qdrant.ensure_collections(dimension=embedder.dimension)

        # 清空旧数据（模型生成的内容）
        if clear_existing:
            logger.info("Clearing existing knowledge collection...")
            try:
                await qdrant.client.delete_collection(self.COLLECTION_NAME)
                await qdrant.ensure_collections(dimension=embedder.dimension)
            except Exception as e:
                logger.warning("Failed to clear collection: %s", e)

        # 分批嵌入和索引
        batch_size = 10  # 阿里云 embedding 限制
        total_indexed = 0

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            texts = [c.to_embedding_text() for c in batch]
            payloads = [c.to_qdrant_payload() for c in batch]

            # 嵌入
            embeddings = await embedder.embed(texts)

            # 索引到 Qdrant
            from qdrant_client.models import PointStruct
            points = [
                PointStruct(
                    id=i + j,
                    vector=embeddings[j],
                    payload=payloads[j],
                )
                for j in range(len(batch))
            ]

            await qdrant.client.upsert(
                collection_name=self.COLLECTION_NAME,
                points=points,
            )
            total_indexed += len(batch)
            logger.info("Indexed %d/%d chunks", total_indexed, len(chunks))

        return total_indexed


# ═══════════════════════════════════════════════════════════════════
# CLI Entry Point
# ═══════════════════════════════════════════════════════════════════

async def build_knowledge_from_pdf(
    pdf_path: str,
    toc_path: str,
    clear_existing: bool = True,
) -> int:
    """从 PDF 构建官方知识库。

    Returns:
        索引的 chunk 数量
    """
    logger.info("Building knowledge base from PDF: %s", pdf_path)

    # 1. Parse TOC
    toc = parse_toc(toc_path)
    logger.info("Loaded %d TOC entries", len(toc))

    # 2. Slice PDF
    slicer = PDFChapterSlicer(pdf_path, toc)
    chunks = slicer.slice()

    # 3. Filter empty/small chunks
    chunks = [c for c in chunks if len(c.content) > 50]
    logger.info("After filtering: %d chunks", len(chunks))

    # 4. Index to Qdrant
    indexer = QdrantKnowledgeIndexer()
    count = await indexer.index_chunks(chunks, clear_existing=clear_existing)

    logger.info("Knowledge base built: %d chunks indexed", count)
    return count


if __name__ == "__main__":
    import asyncio
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    pdf = sys.argv[1] if len(sys.argv) > 1 else "../knowledge/GBase 8a MPP Cluster产品手册_V953.pdf"
    toc = sys.argv[2] if len(sys.argv) > 2 else "../knowledge/official_toc.json"

    asyncio.run(build_knowledge_from_pdf(pdf, toc))
