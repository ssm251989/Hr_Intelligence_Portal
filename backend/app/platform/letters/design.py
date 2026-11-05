"""Part 22.6: one designer for every official letter PDF (offer, joining, appointment / confirmation,
relieving, experience, any HR letter).

Premium and printable:
- brand-colour header band with the logo (in a white tile) and the company name;
- serif headings (Times) + clean sans body (Helvetica) -- the PDF core fonts, so nothing to install;
- a faint watermark of the logo (or the company initials) behind the text;
- reference number + date; a signature block (signatory name, designation, signature image);
- a QR code that opens the public "verify letter" page, plus the short link under it;
- a footer with the company address and CIN on every page.
Celebration accents (confetti + a "Congratulations!" ribbon) ONLY on offer / selection and joining
letters; relieving and experience letters stay formal (they go to banks and future employers).

Core PDF fonts are Latin-1: smart quotes / dashes are swapped for plain ones and the rupee sign is written "Rs.".
"""

import hashlib
import hmac
import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from sqlalchemy.orm import Session

CELEBRATE = {"offer", "selection", "joining", "welcome"}
TITLES = {
    "offer": "Offer Letter", "selection": "Letter of Selection", "joining": "Joining Letter", "welcome": "Joining Letter",
    "appointment": "Appointment Letter", "confirmation": "Confirmation Letter", "relieving": "Relieving Letter",
    "experience": "Experience Certificate", "increment": "Increment Letter", "promotion": "Promotion Letter", "transfer": "Transfer Letter",
}
KIND_CODE = {"offer": "OFR", "selection": "SEL", "joining": "JNG", "welcome": "JNG", "appointment": "APT", "confirmation": "CNF",
             "relieving": "REL", "experience": "EXP", "increment": "INC", "promotion": "PRM", "transfer": "TRF"}
CONFETTI = [(244, 180, 0), (233, 30, 99), (0, 172, 193), (124, 77, 255), (67, 160, 71), (255, 112, 67)]


def safe(text: Optional[str]) -> str:
    return (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').replace("–", "-") \
        .replace("—", "-").replace("•", "-").replace("₹", "Rs.").replace("…", "...").encode("latin-1", "replace").decode("latin-1")


def html_to_text(html_value: Optional[str]) -> str:
    import html as _html

    text = re.sub(r"<br\s*/?>|</p>|</h\d>|</div>|</li>|</tr>", "\n", html_value or "", flags=re.I)
    text = re.sub(r"<li[^>]*>", "- ", text, flags=re.I)
    text = _html.unescape(re.sub(r"<[^>]+>", "", text))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _hex(colour: str) -> tuple[int, int, int]:
    c = (colour or "#0E7C66").lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    try:
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except ValueError:
        return 14, 124, 102


def media_bytes(db: Session, tenant, key: str) -> Optional[bytes]:
    """A company media file (logo, signature) as bytes -- local folder or the storage connection."""
    from app.experience.media_router import MEDIA_DIR, STORAGE_PREFIX, _storage
    from app.models.experience import TenantMedia

    row = db.query(TenantMedia).filter(TenantMedia.tenant_id == tenant.tenant_id, TenantMedia.media_key == key).first()
    if row is None:
        return None
    try:
        if row.file_path.startswith(STORAGE_PREFIX):
            storage = _storage()
            return storage.get(row.file_path[len(STORAGE_PREFIX):]) if storage is not None else None
        p = MEDIA_DIR / row.file_path
        return p.read_bytes() if p.is_file() else None
    except Exception:  # noqa: BLE001 -- a letter never fails over a missing logo
        return None


def _png(data: Optional[bytes]) -> Optional[bytes]:
    """Any raster image -> PNG bytes fpdf can place (None for SVG / unreadable)."""
    if not data:
        return None
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(data))
        im.load()
        out = io.BytesIO()
        im.convert("RGBA").save(out, "PNG")
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return None


def _faded(png: bytes, strength: float = 0.07) -> Optional[bytes]:
    try:
        from PIL import Image

        im = Image.open(io.BytesIO(png)).convert("RGBA")
        white = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(white, im)
        out = Image.blend(white, im, strength)
        buf = io.BytesIO()
        out.convert("RGB").save(buf, "PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


def _qr_png(url: str) -> Optional[bytes]:
    try:
        import segno

        buf = io.BytesIO()
        segno.make(url, error="m").save(buf, kind="png", scale=6, border=1)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        return None


@dataclass
class Brand:
    company: str = ""
    legal_name: str = ""
    colour: tuple = (14, 124, 102)
    logo_png: Optional[bytes] = None
    address: str = ""
    cin: str = ""
    signatory_name: str = ""
    signatory_designation: str = ""
    signature_png: Optional[bytes] = None
    watermark: bool = True
    celebration: bool = True


def brand_for(db: Session, tenant) -> Brand:
    from app.platform.comms.theme import get_theme_and_org_context
    from app.platform.settings.resolver import SettingContext, SettingsService

    s, ctx = SettingsService(db), SettingContext(tenant=tenant)

    def g(key, default=None):
        try:
            v = s.get(key, ctx)
        except Exception:  # noqa: BLE001 -- an unregistered key in an old install
            v = None
        return default if v in (None, "") else v

    theme = get_theme_and_org_context(db, tenant)
    colour = g("letters.brand_colour") or theme["theme"]["primary_color"]
    return Brand(company=g("org.display_name", "") or theme["org"]["display_name"], legal_name=g("org.legal_name", ""), colour=_hex(colour),
                 logo_png=_png(media_bytes(db, tenant, "brand.logo")), address=g("org.address", ""), cin=g("org.cin", ""),
                 signatory_name=g("letters.signatory_name", ""), signatory_designation=g("letters.signatory_designation", ""),
                 signature_png=_png(media_bytes(db, tenant, "letters.signature")), watermark=bool(g("letters.watermark", True)),
                 celebration=bool(g("letters.celebration", True)))


def _initials(company: str) -> str:
    words = re.findall(r"[A-Za-z]+", company or "")
    if words and words[0].isupper() and 2 <= len(words[0]) <= 5:  # "CTD Techs" -> CTD
        return words[0]
    return "".join(w[0] for w in words[:3]).upper() or "HR"


def reference(brand: Brand, kind: str, ident: str, on: date) -> str:
    initials = _initials(brand.company)
    return f"{initials}/HR/{KIND_CODE.get(kind, 'LTR')}/{on.year}/{re.sub(r'[^A-Za-z0-9]', '', str(ident))[:6].upper()}"


# ---- verification (QR) ----

def _secret() -> bytes:
    from app.core.config import settings

    return (getattr(settings, "SECRET_KEY", None) or getattr(settings, "JWT_SECRET_KEY", None) or "letters").encode()


def offer_token(offer_id, version_no: int = 1) -> str:
    """Offers aren't letter_records: their verify token is the id + a keyed signature (nothing to store)."""
    sig = hmac.new(_secret(), f"offer:{offer_id}:{version_no}".encode(), hashlib.sha256).hexdigest()[:16]
    return f"o.{offer_id}.{version_no}.{sig}"


def check_offer_token(token: str) -> Optional[tuple[str, int]]:
    parts = token.split(".")
    if len(parts) != 4 or parts[0] != "o":
        return None
    _, oid, ver, sig = parts
    try:
        good = hmac.compare_digest(offer_token(oid, int(ver)).split(".")[-1], sig)
    except ValueError:
        return None
    return (oid, int(ver)) if good else None


def verify_url(db: Session, token: str) -> str:
    from app.platform.links import public_app_url

    return f"{public_app_url(db)}/verify-letter/{token}"


# ---- the PDF ----

@dataclass
class Letter:
    kind: str
    body: str  # plain text, paragraphs split by blank lines
    reference: str
    issued_on: date
    verify_token: Optional[str] = None
    verify_link: Optional[str] = None
    title: Optional[str] = None
    signed_stamp: Optional[list[str]] = None  # e-signature lines (offer accepted by the candidate)
    extra: dict = field(default_factory=dict)


def render(brand: Brand, letter: Letter) -> bytes:
    from fpdf import FPDF

    celebrate = brand.celebration and letter.kind in CELEBRATE
    r, g, b = brand.colour
    soft = (int(r + (255 - r) * 0.88), int(g + (255 - g) * 0.88), int(b + (255 - b) * 0.88))
    watermark = _faded(brand.logo_png) if (brand.watermark and brand.logo_png) else None
    initials = _initials(brand.company) if brand.company else ""

    class Doc(FPDF):
        def header(self):
            w = self.w
            if self.page_no() == 1:
                self.set_fill_color(r, g, b)
                self.rect(0, 0, w, 34, "F")
                self.set_fill_color(*soft)
                self.rect(0, 34, w, 2.2, "F")
                if celebrate:  # confetti in the band
                    import random

                    rnd = random.Random(letter.reference)
                    for _ in range(46):
                        self.set_fill_color(*rnd.choice(CONFETTI))
                        x, y, s = rnd.uniform(w * 0.45, w - 6), rnd.uniform(3, 31), rnd.uniform(1.2, 2.6)
                        if rnd.random() < 0.5:
                            self.rect(x, y, s, s * 0.55, "F")
                        else:
                            self.polygon([(x, y), (x + s, y + s * 0.4), (x + s * 0.2, y + s)], style="F")
                x0 = 14
                if brand.logo_png:
                    self.set_fill_color(255, 255, 255)
                    self.rect(x0, 7, 30, 20, "F")
                    try:
                        self.image(io.BytesIO(brand.logo_png), x=x0 + 2, y=9, w=26, h=16, keep_aspect_ratio=True)
                    except Exception:  # noqa: BLE001
                        pass
                    x0 += 36
                self.set_text_color(255, 255, 255)
                self.set_xy(x0, 9)
                self.set_font("Times", "B", 20)
                self.cell(0, 9, safe(brand.company or "Human Resources"))
                self.set_xy(x0, 19)
                self.set_font("Helvetica", "", 9)
                self.cell(0, 6, safe(brand.legal_name if brand.legal_name and brand.legal_name != brand.company else "Human Resources"))
                self.set_text_color(40, 40, 40)
                self.set_y(44)
            else:
                self.set_fill_color(r, g, b)
                self.rect(0, 0, self.w, 6, "F")
                self.set_y(14)
            if watermark:
                try:
                    self.image(io.BytesIO(watermark), x=self.w / 2 - 45, y=self.h / 2 - 35, w=90, keep_aspect_ratio=True)
                except Exception:  # noqa: BLE001
                    pass
            elif brand.watermark and initials:
                self.set_text_color(243, 243, 243)
                self.set_font("Times", "B", 120)
                with self.rotation(30, self.w / 2, self.h / 2):
                    self.text(self.w / 2 - 40, self.h / 2 + 15, initials)
                self.set_text_color(40, 40, 40)

        def footer(self):
            self.set_y(-20)
            self.set_draw_color(r, g, b)
            self.set_line_width(0.4)
            self.line(14, self.get_y(), self.w - 14, self.get_y())
            self.ln(1.5)
            self.set_font("Helvetica", "", 7.5)
            self.set_text_color(110, 110, 110)
            bits = [brand.legal_name or brand.company, brand.address, f"CIN: {brand.cin}" if brand.cin else ""]
            self.multi_cell(0, 3.6, safe("  |  ".join(x for x in bits if x)), align="C", new_x="LMARGIN", new_y="NEXT")
            self.set_font("Helvetica", "", 7)
            self.cell(0, 4, safe(f"Ref {letter.reference}   -   Page {self.page_no()} of {{nb}}"), align="C")
            self.set_text_color(40, 40, 40)

    pdf = Doc(format="A4")
    pdf.alias_nb_pages()
    pdf.set_margins(18, 14, 18)
    pdf.set_auto_page_break(True, margin=26)
    pdf.add_page()
    nl = {"new_x": "LMARGIN", "new_y": "NEXT"}

    # reference + date (right), ribbon (left) on celebration letters
    y = pdf.get_y()
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.set_xy(pdf.w - 18 - 80, y)
    pdf.multi_cell(80, 4.6, safe(f"Ref: {letter.reference}\nDate: {letter.issued_on.strftime('%d %B %Y')}"), align="R", **nl)
    if celebrate:
        pdf.set_fill_color(*CONFETTI[1])
        pdf.polygon([(18, y), (78, y), (73, y + 5), (78, y + 10), (18, y + 10)], style="F")
        pdf.set_xy(20, y + 1.6)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Times", "BI", 13)
        pdf.cell(54, 7, "Congratulations!")
    pdf.set_text_color(40, 40, 40)
    pdf.set_y(y + 16)

    # title
    pdf.set_font("Times", "B", 19)
    pdf.set_text_color(r, g, b)
    pdf.cell(0, 9, safe(letter.title or TITLES.get(letter.kind, "Letter")), **nl)
    pdf.set_draw_color(r, g, b)
    pdf.set_line_width(0.8)
    pdf.line(18, pdf.get_y() + 1, 58, pdf.get_y() + 1)
    pdf.ln(6)
    pdf.set_text_color(40, 40, 40)

    # body
    pdf.set_font("Helvetica", "", 10.5)
    for para in [p.strip() for p in re.split(r"\n\s*\n", letter.body or "") if p.strip()]:
        lines = para.splitlines()
        if len(lines) == 1 and len(para) < 70 and (para.endswith(":") or para.isupper()):
            pdf.set_font("Helvetica", "B", 10.5)
            pdf.multi_cell(0, 5.6, safe(para), **nl)
            pdf.set_font("Helvetica", "", 10.5)
        else:
            pdf.multi_cell(0, 5.6, safe("\n".join(lines)), **nl)
        pdf.ln(2.4)

    # signature block (+ QR on the right)
    if pdf.get_y() > pdf.h - 80:
        pdf.add_page()
    pdf.ln(4)
    top = pdf.get_y()
    pdf.set_font("Helvetica", "", 10.5)
    pdf.cell(0, 5.6, safe(f"For {brand.legal_name or brand.company}"), **nl)
    if brand.signature_png:
        try:
            pdf.image(io.BytesIO(brand.signature_png), x=18, y=pdf.get_y() + 1, h=16, keep_aspect_ratio=True)
        except Exception:  # noqa: BLE001
            pass
        pdf.ln(18)
    else:
        pdf.ln(12)
    pdf.set_draw_color(150, 150, 150)
    pdf.set_line_width(0.2)
    pdf.line(18, pdf.get_y(), 78, pdf.get_y())
    pdf.ln(1.5)
    pdf.set_font("Times", "B", 11.5)
    pdf.cell(0, 5.6, safe(brand.signatory_name or "Authorised Signatory"), **nl)
    pdf.set_font("Helvetica", "", 9.5)
    pdf.cell(0, 5, safe(brand.signatory_designation or "Human Resources"), **nl)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 4.5, "Digitally issued - no physical signature required.", **nl)
    pdf.set_text_color(40, 40, 40)
    bottom = pdf.get_y()
    if letter.verify_link:
        qr = _qr_png(letter.verify_link)
        if qr:
            pdf.image(io.BytesIO(qr), x=pdf.w - 18 - 30, y=top, w=30, h=30)
            pdf.set_xy(pdf.w - 18 - 90, top + 31)
            pdf.set_font("Helvetica", "B", 7.5)
            pdf.multi_cell(90, 3.6, "Scan to verify this letter", align="R", **nl)
            pdf.set_x(pdf.w - 18 - 90)
            pdf.set_font("Helvetica", "", 6)
            pdf.set_text_color(110, 110, 110)
            pdf.multi_cell(90, 3.2, safe(letter.verify_link), align="R", **nl)
            pdf.set_text_color(40, 40, 40)
            bottom = max(bottom, pdf.get_y())
    pdf.set_y(bottom + 4)

    if letter.signed_stamp:  # the candidate's e-signature (offer letters)
        pdf.set_draw_color(r, g, b)
        pdf.set_fill_color(*soft)
        pdf.set_font("Helvetica", "B", 10)
        pdf.multi_cell(0, 6.5, safe(letter.signed_stamp[0]), border="LTR", fill=True, **nl)
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5.2, safe("\n".join(letter.signed_stamp[1:])), border="LBR", fill=True, **nl)
    return bytes(pdf.output())


def letter_record_pdf(db: Session, record) -> bytes:
    """Any letter_records row (joining, appointment, confirmation, relieving, experience ...)."""
    from app.platform.tenancy.context import require_current_tenant

    tenant = require_current_tenant()
    brand = brand_for(db, tenant)
    kind = _kind(record.template_key)
    issued = record.generated_at.date() if record.generated_at else date.today()
    return render(brand, Letter(kind=kind, body=html_to_text(record.rendered_html), reference=reference(brand, kind, record.id.hex, issued),
                                issued_on=issued, verify_token=record.verification_token,
                                verify_link=verify_url(db, record.verification_token)))


def _kind(template_key: str) -> str:
    k = (template_key or "").lower()
    for kind in ("relieving", "experience", "appointment", "confirmation", "joining", "welcome", "offer", "increment", "promotion", "transfer"):
        if kind in k:
            return kind
    return "letter"
