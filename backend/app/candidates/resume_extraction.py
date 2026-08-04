import io

from docx import Document
from pypdf import PdfReader


class UnsupportedFileTypeError(Exception):
    pass


class ResumeExtractionError(Exception):
    pass


def extract_text(file_bytes: bytes, filename: str) -> str:
    extension = filename.lower().rsplit(".", 1)[-1] if filename and "." in filename else ""
    if extension == "pdf":
        return _extract_pdf(file_bytes)
    if extension == "docx":
        return _extract_docx(file_bytes)
    raise UnsupportedFileTypeError(f"Unsupported file type: .{extension}")


def _extract_pdf(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:
        raise ResumeExtractionError(str(exc)) from exc


def _extract_docx(file_bytes: bytes) -> str:
    try:
        document = Document(io.BytesIO(file_bytes))
        return "\n".join(p.text for p in document.paragraphs).strip()
    except Exception as exc:
        raise ResumeExtractionError(str(exc)) from exc
