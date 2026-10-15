"""Parse private knowledge files into bounded, source-addressable text chunks."""

import re
from dataclasses import dataclass
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

from app.common.exceptions import BusinessException


MAX_DOCX_UNCOMPRESSED_BYTES = 20 * 1024 * 1024
SUPPORTED_SUFFIXES = {".txt", ".md", ".docx", ".pdf"}


@dataclass(frozen=True)
class ParsedChunk:
    text: str
    page: int | None = None
    section: str | None = None


def _read_text(path: Path, max_chars: int) -> str:
    with path.open("r", encoding="utf-8-sig") as document:
        text = document.read(max_chars + 1)
    if len(text) > max_chars:
        raise BusinessException("文档解析后的字数超过限制，请拆分后上传")
    return text


def _markdown_blocks(text: str) -> list[ParsedChunk]:
    blocks = []
    lines = []
    headings = []
    section = None
    in_code_block = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_code_block = not in_code_block
        heading = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
        if heading and not in_code_block:
            if lines:
                blocks.append(ParsedChunk("\n".join(lines), section=section))
            level = len(heading.group(1))
            headings = [(depth, title) for depth, title in headings if depth < level]
            headings.append((level, heading.group(2)))
            section = " / ".join(title for _, title in headings)
            lines = []
        lines.append(line)
    if lines:
        blocks.append(ParsedChunk("\n".join(lines), section=section))
    return blocks


def _check_docx_archive(path: Path) -> None:
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 20_000 or sum(entry.file_size for entry in entries) > MAX_DOCX_UNCOMPRESSED_BYTES:
            raise BusinessException("Word 文档解压后体积过大，请精简后上传")
        if any(entry.flag_bits & 1 for entry in entries):
            raise BusinessException("暂不支持加密的 Word 文档")
        if any("vbaproject" in entry.filename.lower() for entry in entries):
            raise BusinessException("暂不支持包含宏的 Word 文档")
        if "[Content_Types].xml" in archive.namelist():
            content_types = archive.read("[Content_Types].xml").lower()
            if b"macroenabled" in content_types or b"vbaproject" in content_types:
                raise BusinessException("暂不支持包含宏的 Word 文档")


def _docx_blocks(path: Path) -> list[ParsedChunk]:
    _check_docx_archive(path)
    document = Document(path)
    blocks = []
    heading = None
    paragraph_number = 0
    table_number = 0
    for element in document.element.body.iterchildren():
        if isinstance(element, CT_P):
            paragraph_number += 1
            paragraph = Paragraph(element, document)
            text = paragraph.text.strip()
            if not text:
                continue
            if paragraph.style and paragraph.style.name.lower().startswith("heading"):
                heading = text
            location = f"段落 {paragraph_number}"
            section = f"{heading} · {location}" if heading else location
            blocks.append(ParsedChunk(text, section=section))
        elif isinstance(element, CT_Tbl):
            table_number += 1
            table = Table(element, document)
            if not table.rows:
                continue
            headers = [cell.text.strip().replace("\n", " / ") for cell in table.rows[0].cells]
            location = f"表格 {table_number}"
            section = f"{heading} · {location}" if heading else location
            if any(headers):
                blocks.append(ParsedChunk(f"{location} 表头：{' | '.join(headers)}", section=section))
            for row_number, row in enumerate(table.rows[1:], start=2):
                values = []
                for column_number, cell in enumerate(row.cells):
                    value = cell.text.strip().replace("\n", " / ")
                    label = headers[column_number] if column_number < len(headers) else ""
                    label = label or f"第 {column_number + 1} 列"
                    if value:
                        values.append(f"{label}：{value}")
                if values:
                    blocks.append(ParsedChunk(
                        f"{location} 第 {row_number} 行：{'；'.join(values)}",
                        section=f"{section} · 第 {row_number} 行",
                    ))
    return blocks


def _pdf_blocks(path: Path, max_chars: int, max_pages: int) -> list[ParsedChunk]:
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise BusinessException("暂不支持加密的 PDF，请解密后上传")
    if len(reader.pages) > max_pages:
        raise BusinessException("PDF 页数超过限制，请拆分后上传")
    blocks = []
    character_count = 0
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        character_count += len(text)
        if character_count > max_chars:
            raise BusinessException("文档解析后的字数超过限制，请拆分后上传")
        if text.strip():
            blocks.append(ParsedChunk(text, page=page_number))
    if not blocks:
        raise BusinessException("PDF 没有可提取的文字，暂不支持扫描件，请上传带文字层的文档")
    return blocks


def parse_document(
    path: Path,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
    max_chars: int = 500_000,
    max_pages: int = 200,
) -> list[ParsedChunk]:
    """Extract local text without OCR or resolving document external references.

    PDF pages and Word paragraphs/table rows remain separate source units so a
    resulting citation always identifies its actual location in the document.
    """
    if (
        chunk_size <= 0
        or chunk_overlap < 0
        or chunk_overlap >= chunk_size
        or max_chars <= 0
        or max_pages <= 0
    ):
        raise BusinessException("文档切分配置无效，请检查字数、页数和重叠长度")
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise BusinessException("暂不支持该文件格式，请上传 TXT、MD、DOCX 或带文字层的 PDF")
    try:
        if suffix in {".txt", ".md"}:
            text = _read_text(path, max_chars)
            blocks = _markdown_blocks(text) if suffix == ".md" else [ParsedChunk(text)]
        elif suffix == ".docx":
            blocks = _docx_blocks(path)
        else:
            blocks = _pdf_blocks(path, max_chars, max_pages)
        if sum(len(block.text) for block in blocks) > max_chars:
            raise BusinessException("文档解析后的字数超过限制，请拆分后上传")
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""],
        )
        chunks = [
            ParsedChunk(text, page=block.page, section=block.section)
            for block in blocks
            for text in splitter.split_text(block.text)
            if text.strip()
        ]
        if not chunks:
            raise BusinessException("文档内容为空，请上传包含文字的文档")
        return chunks
    except BusinessException:
        raise
    except UnicodeDecodeError:
        raise BusinessException("文本文件编码不受支持，请转换为 UTF-8 后上传") from None
    except Exception:
        raise BusinessException("文档解析失败，请检查文件是否完整且格式正确") from None
