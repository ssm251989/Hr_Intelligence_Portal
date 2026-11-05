"""Multi-currency amounts (docs/HRMS_COMPLETE_SPEC.txt Part 6 section 6's own "(amount,
currency) with FX table") -- a manually-maintained rate table, no live provider feed (see
app.models.metadata.FxRate's own docstring)."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from app.models.metadata import FxRate
from app.platform.tenancy.context import TenantContext

CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


class RateNotFoundError(Exception):
    pass


def set_rate(db: Session, tenant: TenantContext, *, from_currency: str, to_currency: str, rate: Decimal, as_of: Optional[datetime] = None) -> FxRate:
    as_of = as_of or datetime.now(timezone.utc)
    existing = (
        db.query(FxRate)
        .filter(FxRate.tenant_id == tenant.tenant_id, FxRate.from_currency == from_currency, FxRate.to_currency == to_currency, FxRate.as_of_date == as_of)
        .first()
    )
    if existing is not None:
        existing.rate = rate
        db.commit()
        db.refresh(existing)
        return existing
    row = FxRate(tenant_id=tenant.tenant_id, from_currency=from_currency, to_currency=to_currency, rate=rate, as_of_date=as_of)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def latest_rate(db: Session, tenant: TenantContext, from_currency: str, to_currency: str) -> Decimal:
    if from_currency == to_currency:
        return Decimal("1")
    row = (
        db.query(FxRate)
        .filter(FxRate.tenant_id == tenant.tenant_id, FxRate.from_currency == from_currency, FxRate.to_currency == to_currency)
        .order_by(FxRate.as_of_date.desc())
        .first()
    )
    if row is None:
        raise RateNotFoundError(f"No FX rate on file for {from_currency}->{to_currency}")
    return row.rate


def convert(db: Session, tenant: TenantContext, amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
    return amount * latest_rate(db, tenant, from_currency, to_currency)


def format_amount(amount: Decimal, currency: str) -> str:
    symbol = CURRENCY_SYMBOLS.get(currency, currency + " ")
    return f"{symbol}{amount:,.2f}"
