"""Which identifier to hand to data providers for a company."""

from app.models import Company


def provider_symbol(company: Company) -> str:
    """NSE symbol for NSE-listed companies; BSE scrip code for companies listed only on BSE."""
    if company.exchange == "BSE" and company.bse_code:
        return company.bse_code
    return company.symbol
