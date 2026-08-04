from app.candidates.resume_extraction import extract_text

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png"}


def extract_bgv_text(file_bytes: bytes, filename: str) -> str:
    extension = filename.lower().rsplit(".", 1)[-1] if filename and "." in filename else ""
    if extension in IMAGE_EXTENSIONS:
        # Real OCR is not wired up yet for image-based BGV documents (Aadhaar/PAN
        # scans are commonly JPG/PNG). This placeholder lets the Document
        # Validator still receive *something* to reason about instead of
        # failing the upload outright -- accuracy on image docs will be poor
        # until OCR is added.
        return f"[Image document: {filename} — OCR not implemented, no extracted text available]"
    return extract_text(file_bytes, filename)
