"""Billing provider seam (NOT wired to any payment network).

All commercial mutations go through `record_*` helpers here so a real
provider (Paystack / Flutterwave) slots in later: implement `charge`,
`refund` and `sync_status`, flip `PROVIDER_NAME`, and nothing else
changes. Until then every invoice is provider='manual' and every charge
is recorded, never executed.
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("cyphward.billing")

PROVIDER_NAME = "manual"

# NGN per month. Sovereign is custom-scoped (no automatic invoice).
PLAN_PRICES_KOBO = {
    "growth": 45_000_000,    # ₦450,000
    "scale": 185_000_000,    # ₦1,850,000
    "sovereign": 0,
}


class BillingProvider:
    name = PROVIDER_NAME

    def charge(self, invoice: Dict[str, Any]) -> Dict[str, Any]:
        """Record (never execute) a charge for a manual invoice."""
        logger.info("billing(manual): recorded %s kobo invoice %s (no provider call)",
                    invoice.get("amount_kobo"), invoice.get("id"))
        return {"provider": self.name, "provider_ref": None, "charged": False}

    def refund(self, invoice: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("billing(manual): recorded refund request for %s (no provider call)",
                    invoice.get("id"))
        return {"provider": self.name, "refunded": False}

    def sync_status(self, subscription: Dict[str, Any]) -> Optional[str]:
        """Return a provider-side status override, or None when unwired."""
        return None


provider = BillingProvider()
