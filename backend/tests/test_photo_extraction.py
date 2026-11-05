import io

from docx import Document
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject, StreamObject

from app.candidates.photo_extraction import extract_photo


def _make_image_bytes(size=(4, 4), color=(200, 50, 50), fmt="PNG") -> bytes:
    image = Image.new("RGB", size, color=color)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def _make_docx_bytes(text: str = "Jane Doe", photo_bytes: bytes | None = None) -> bytes:
    document = Document()
    document.add_paragraph(text)
    if photo_bytes is not None:
        document.add_picture(io.BytesIO(photo_bytes))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _make_pdf_bytes(jpeg_bytes: bytes | None = None, width: int = 4, height: int = 4) -> bytes:
    # pypdf's PdfWriter has no high-level "add image" API -- an embedded image is a raw
    # XObject stream referenced from the page's /Resources, built here at the same
    # generic-object level pypdf itself reads it back through (see photo_extraction.py's
    # use of page.images, which decodes exactly this structure).
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)

    if jpeg_bytes is not None:
        image_stream = StreamObject()
        image_stream.set_data(jpeg_bytes)
        image_stream[NameObject("/Type")] = NameObject("/XObject")
        image_stream[NameObject("/Subtype")] = NameObject("/Image")
        image_stream[NameObject("/Width")] = NumberObject(width)
        image_stream[NameObject("/Height")] = NumberObject(height)
        image_stream[NameObject("/ColorSpace")] = NameObject("/DeviceRGB")
        image_stream[NameObject("/BitsPerComponent")] = NumberObject(8)
        image_stream[NameObject("/Filter")] = NameObject("/DCTDecode")
        image_ref = writer._add_object(image_stream)

        if "/Resources" not in page:
            page[NameObject("/Resources")] = DictionaryObject()
        resources = page["/Resources"].get_object()
        if "/XObject" not in resources:
            resources[NameObject("/XObject")] = DictionaryObject()
        resources["/XObject"][NameObject("/Im0")] = image_ref

    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def test_extract_photo_from_docx_with_embedded_image():
    photo_bytes = _make_image_bytes(fmt="PNG")
    docx_bytes = _make_docx_bytes(photo_bytes=photo_bytes)

    result = extract_photo(docx_bytes, "resume.docx")

    assert result is not None
    image_bytes, extension = result
    assert image_bytes == photo_bytes
    assert extension == "png"


def test_extract_photo_from_pdf_with_embedded_image():
    jpeg_bytes = _make_image_bytes(fmt="JPEG")
    pdf_bytes = _make_pdf_bytes(jpeg_bytes=jpeg_bytes)

    result = extract_photo(pdf_bytes, "resume.pdf")

    assert result is not None
    image_bytes, extension = result
    assert image_bytes == jpeg_bytes
    assert extension in ("jpg", "jpeg")


def test_extract_photo_from_docx_without_image_returns_none():
    docx_bytes = _make_docx_bytes(photo_bytes=None)

    assert extract_photo(docx_bytes, "resume.docx") is None


def test_extract_photo_from_pdf_without_image_returns_none():
    pdf_bytes = _make_pdf_bytes(jpeg_bytes=None)

    assert extract_photo(pdf_bytes, "resume.pdf") is None


def test_extract_photo_unsupported_extension_returns_none():
    assert extract_photo(b"plain text resume", "resume.txt") is None
    assert extract_photo(b"plain text resume", "resume") is None


def test_extract_photo_corrupt_file_does_not_raise():
    # Garbage bytes with a real extension -- must fail closed (None), never propagate an
    # exception, since a corrupt or unreadable file is exactly the case the parse flow
    # must be able to shrug off.
    assert extract_photo(b"not a real docx file", "resume.docx") is None
    assert extract_photo(b"not a real pdf file", "resume.pdf") is None


def test_extracted_pdf_photo_is_reopenable_as_a_real_image():
    # Round-trip sanity check: what the function extracts is a genuine, decodable image,
    # not just an arbitrary byte slice that happens to satisfy the other assertions.
    jpeg_bytes = _make_image_bytes(fmt="JPEG", color=(10, 20, 30))
    pdf_bytes = _make_pdf_bytes(jpeg_bytes=jpeg_bytes)

    image_bytes, extension = extract_photo(pdf_bytes, "resume.pdf")
    reopened = Image.open(io.BytesIO(image_bytes))
    reopened.load()
    assert extension in ("jpg", "jpeg")
    assert reopened.size == (4, 4)


# Sanity check that the hand-built PDF fixture itself is valid and pypdf can read it back
# at all -- if this ever breaks, the two PDF tests above are failing for a fixture reason,
# not a photo_extraction.py reason.
def test_pdf_fixture_is_a_valid_readable_pdf():
    pdf_bytes = _make_pdf_bytes(jpeg_bytes=_make_image_bytes(fmt="JPEG"))
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 1
