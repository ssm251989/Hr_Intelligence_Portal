import io
from typing import Optional

from docx import Document
from pypdf import PdfReader


def extract_photo(file_bytes: bytes, filename: str) -> Optional[tuple[bytes, str]]:
    """Best-effort extraction of a candidate's embedded photo from their resume (common in
    this market) -- returns (image_bytes, extension) for the first embedded image found, or
    None if there isn't one. Unlike resume_extraction.extract_text (which raises on failure
    so the upload endpoint can reject an unreadable file), this never raises: a resume with
    no photo, an unsupported file type, or a file this can't be parsed for images at all
    must never block or fail the existing resume-parsing flow -- a missing photo is just as
    valid an outcome as a present one.
    """
    try:
        extension = filename.lower().rsplit(".", 1)[-1] if filename and "." in filename else ""
        if extension == "docx":
            return _extract_docx_photo(file_bytes)
        if extension == "pdf":
            return _extract_pdf_photo(file_bytes)
        return None
    except Exception:
        return None


def _extract_docx_photo(file_bytes: bytes) -> Optional[tuple[bytes, str]]:
    # A .docx is a zip of parts; embedded images are just another related part (under
    # word/media/) rather than something python-docx surfaces via a dedicated "photo" API --
    # the first image relationship found is taken as the candidate's photo.
    document = Document(io.BytesIO(file_bytes))
    for rel in document.part.rels.values():
        if "image" in rel.reltype:
            image_part = rel.target_part
            extension = str(image_part.partname).rsplit(".", 1)[-1].lower()
            return image_part.blob, extension
    return None


def _extract_pdf_photo(file_bytes: bytes) -> Optional[tuple[bytes, str]]:
    # pypdf's page.images needs Pillow installed (see requirements.txt) to decode the
    # embedded XObject back into real image bytes.
    reader = PdfReader(io.BytesIO(file_bytes))
    for page in reader.pages:
        for image_file in page.images:
            extension = image_file.name.rsplit(".", 1)[-1].lower() if "." in image_file.name else "png"
            return image_file.data, extension
    return None
