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

# NGN per month. Retired tiers never invoice (custom/legacy handling).
PLAN_PRICES_KOBO = {
    "starter": 700_000,      # ₦7,000
    "growth": 1_500_000,     # ₦15,000
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
