import io
import re
import struct

from docx import Document
from pypdf import PdfReader


class UnsupportedFileTypeError(Exception):
    pass


class ResumeExtractionError(Exception):
    pass


# Part 18 fix: below this many letters a PDF has no usable text layer (a scan / photo of a
# resume), so the parser reads the file itself with Claude vision instead (see
# resume_parser.parse_resume's `file_bytes`).
MIN_TEXT_LETTERS = 80

IMAGE_MEDIA_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def extension_of(filename: str) -> str:
    return filename.lower().rsplit(".", 1)[-1] if filename and "." in filename else ""


def extract_text(file_bytes: bytes, filename: str) -> str:
    extension = extension_of(filename)
    if extension == "pdf":
        return _extract_pdf(file_bytes)
    if extension == "docx":
        return _extract_docx(file_bytes)
    if extension == "doc":
        return _extract_doc(file_bytes)
    if extension in IMAGE_MEDIA_TYPES:
        return ""  # an image has no text layer -- always read with vision
    raise UnsupportedFileTypeError(f"Unsupported file type: .{extension}")


def needs_vision(text: str) -> bool:
    """True when the extracted text is too thin to parse (scanned PDF, photo of a resume)."""
    return sum(ch.isalpha() for ch in text or "") < MIN_TEXT_LETTERS


def vision_media_type(filename: str) -> str | None:
    """The media type Claude can read directly for this file, or None (docx/doc)."""
    extension = extension_of(filename)
    if extension == "pdf":
        return "application/pdf"
    return IMAGE_MEDIA_TYPES.get(extension)


def _extract_pdf(file_bytes: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as exc:
        raise ResumeExtractionError(str(exc)) from exc


def _extract_docx(file_bytes: bytes) -> str:
    try:
        document = Document(io.BytesIO(file_bytes))
        parts = [p.text for p in document.paragraphs]
        # Resumes often keep contact details / skills in tables, which paragraphs miss.
        for table in document.tables:
            for row in table.rows:
                parts.append("\t".join(cell.text for cell in row.cells))
        return "\n".join(parts).strip()
    except Exception as exc:
        raise ResumeExtractionError(str(exc)) from exc


def _extract_doc(file_bytes: bytes) -> str:
    """Old Word 97-2003 .doc: text via the document's piece table (no Word / LibreOffice needed)."""
    try:
        import olefile

        ole = olefile.OleFileIO(io.BytesIO(file_bytes))
        word = ole.openstream("WordDocument").read()
        flags = struct.unpack_from("<H", word, 0x0A)[0]
        table = ole.openstream("1Table" if flags & 0x0200 else "0Table").read()
        fc_clx, lcb_clx = struct.unpack_from("<II", word, 0x01A2)
        clx = table[fc_clx:fc_clx + lcb_clx]
        pos = 0
        while pos < len(clx) and clx[pos] == 0x01:  # skip Prc entries
            pos += 3 + struct.unpack_from("<H", clx, pos + 1)[0]
        if pos >= len(clx) or clx[pos] != 0x02:
            raise ResumeExtractionError("no piece table")
        lcb = struct.unpack_from("<I", clx, pos + 1)[0]
        plc = clx[pos + 5:pos + 5 + lcb]
        n = (lcb - 4) // 12
        cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
        out = []
        for i in range(n):
            fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * i + 2)[0]
            count = cps[i + 1] - cps[i]
            if fc & 0x40000000:
                start = (fc & 0x3FFFFFFF) // 2
                out.append(word[start:start + count].decode("cp1252", errors="replace"))
            else:
                out.append(word[fc:fc + 2 * count].decode("utf-16-le", errors="replace"))
        text = "".join(out)
    except ResumeExtractionError:
        raise
    except Exception as exc:
        raise ResumeExtractionError(f"Could not read the .doc file: {exc}") from exc
    text = re.sub(r"\x13[^\x14\x15]*\x14?", "", text).replace("\x15", "")  # field codes -> results
    text = text.replace("\r", "\n").replace("\x07", "\t").replace("\x0b", "\n").replace("\x0c", "\n")
    # Word sometimes stores smart quotes / dashes as C1 codes (U+0080-U+009F) -> their cp1252 characters
    text = re.sub(r"[\x80-\x9f]", lambda m: bytes([ord(m.group())]).decode("cp1252", errors="ignore"), text)
    text = re.sub(r"[\x00-\x08\x0e-\x1f]", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
