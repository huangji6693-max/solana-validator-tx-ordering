from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional


class RouteMode(str, Enum):
    STANDARD = "STANDARD"
    CUSTOM_HOP = "CUSTOM_HOP"
    RANDOMIZED_UNBUNDLED = "RANDOMIZED_UNBUNDLED"
    MULTI_SEND = "MULTI_SEND"
    SWAP_WITH_HOOK = "SWAP_WITH_HOOK"


class ComplianceStatus(str, Enum):
    APPROVED = "APPROVED"
    FLAGGED_HIGH_RISK = "FLAGGED_HIGH_RISK"
    SANCTIONED_BLOCKED = "SANCTIONED_BLOCKED"


@dataclass(frozen=True)
class TrmScreeningResult:
    address: str
    status: ComplianceStatus
    risk_score: int
    reason: Optional[str] = None

    @property
    def is_compliant(self) -> bool:
        return self.status == ComplianceStatus.APPROVED and self.risk_score < 70


@dataclass(frozen=True)
class RecipientAllocation:
    recipient: str
    amount_usdc: float
    memo: str = ""


@dataclass(frozen=True)
class HopStep:
    hop_index: int
    ephemeral_relay: str
    delay_ms: int
    amount_usdc: float


@dataclass
class RoutedSettlementReceipt:
    route_id: str
    integration_id: str
    sender: str
    token_mint: str
    mode: RouteMode
    principal_usdc: float
    full_fee_bps: int
    total_fee_usdc: float
    partner_revenue_usdc: float
    pool_contribution_usdc: float
    qualifying_volume_usdc: float
    hops: List[HopStep]
    recipients: List[RecipientAllocation]
    trm_checks: List[TrmScreeningResult]
    tx_signatures: List[str]
    created_at_unix: int = field(default_factory=lambda: int(time.time()))

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)


class TrmComplianceGate:
    """
    Simulates MultiHopper's built-in smart-contract and routing-level TRM Labs compliance screening.
    """

    def __init__(self, blocked_prefixes: Optional[List[str]] = None) -> None:
        self.blocked_prefixes = tuple(blocked_prefixes or ["OFAC", "SANCTION", "DARK", "MIXER"])

    def screen_address(self, address: str) -> TrmScreeningResult:
        cleaned = (address or "").strip()
        if not cleaned or len(cleaned) < 32:
            return TrmScreeningResult(
                address=cleaned,
                status=ComplianceStatus.FLAGGED_HIGH_RISK,
                risk_score=95,
                reason="Invalid Solana base58 address length",
            )
        upper = cleaned.upper()
        for prefix in self.blocked_prefixes:
            if upper.startswith(prefix):
                return TrmScreeningResult(
                    address=cleaned,
                    status=ComplianceStatus.SANCTIONED_BLOCKED,
                    risk_score=100,
                    reason=f"Matched TRM sanctions/risk rule: {prefix}",
                )
        return TrmScreeningResult(
            address=cleaned,
            status=ComplianceStatus.APPROVED,
            risk_score=5,
            reason="Clean on-chain provenance",
        )


class MultiHopperRouter:
    """
    Programmable Solana settlement & Multi-Send router built on MultiHopper's routing specification:
    - 0.50% (50 bps) full-rate transfer fee
    - 0.25% (25 bps) direct partner revenue share ($2,500 per $1,000,000 routed)
    - 0.25% (25 bps) competition pool contribution
    - Non-commingled multi-hop & Multi-Send execution with TRM Labs compliance gating
    """

    FULL_RATE_FEE_BPS = 50       # 0.50%
    PARTNER_SHARE_BPS = 25       # 0.25%
    POOL_SHARE_BPS = 25          # 0.25%

    def __init__(
        self,
        integration_id: str = "mh_partner_sol_treasury_v1",
        webhook_secret: str = "mh_whsec_default_signing_key",
        compliance_gate: Optional[TrmComplianceGate] = None,
    ) -> None:
        self.integration_id = integration_id
        self.webhook_secret = webhook_secret
        self.compliance_gate = compliance_gate or TrmComplianceGate()
        self._executed_routes: Dict[str, RoutedSettlementReceipt] = {}

    def verify_completion_webhook(self, payload_bytes: bytes, signature_hex: str) -> bool:
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature_hex)

    def sign_completion_webhook(self, payload_bytes: bytes) -> str:
        return hmac.new(
            self.webhook_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()

    def execute_routed_settlement(
        self,
        sender: str,
        recipients: List[RecipientAllocation],
        token_mint: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        mode: RouteMode = RouteMode.MULTI_SEND,
        num_hops: int = 2,
        fee_bps: int = FULL_RATE_FEE_BPS,
        is_devnet: bool = False,
    ) -> RoutedSettlementReceipt:
        if not recipients:
            raise ValueError("At least one recipient allocation is required")
        if num_hops < 1 or num_hops > 5:
            raise ValueError("num_hops must be between 1 and 5")
        if fee_bps < 0 or fee_bps > 500:
            raise ValueError("fee_bps out of bounds")

        # 1. Screen sender and all recipients via TRM Labs compliance gate
        trm_checks: List[TrmScreeningResult] = [self.compliance_gate.screen_address(sender)]
        for r in recipients:
            if r.amount_usdc <= 0:
                raise ValueError(f"Recipient amount must be positive for {r.recipient}")
            if r.recipient == sender:
                raise ValueError("Circular self-transfer is excluded from qualifying routing")
            trm_checks.append(self.compliance_gate.screen_address(r.recipient))

        for check in trm_checks:
            if not check.is_compliant:
                raise PermissionError(
                    f"TRM Compliance Gate blocked address {check.address}: {check.reason}"
                )

        # 2. Calculate principal once (hops and Multi-Send recipients never multiply principal volume)
        principal_usdc = round(sum(r.amount_usdc for r in recipients), 6)
        total_fee_usdc = round(principal_usdc * (fee_bps / 10_000.0), 6)
        partner_revenue_usdc = round(total_fee_usdc * 0.5, 6)
        pool_contribution_usdc = round(total_fee_usdc - partner_revenue_usdc, 6)

        # Qualifying volume = collected MultiHopper percentage fees / 0.0025 (discounted transfers count proportionally; devnet = 0)
        if is_devnet or fee_bps == 0:
            qualifying_volume_usdc = 0.0
        else:
            # Collected MultiHopper share is half of total percentage fee = principal * (fee_bps / 20000)
            qualifying_volume_usdc = round(pool_contribution_usdc / 0.0025, 6)

        # 3. Construct non-commingled relay hops
        route_id = f"route_{uuid.uuid4().hex[:16]}"
        hops: List[HopStep] = []
        tx_signatures: List[str] = []

        for idx in range(1, num_hops + 1):
            relay_seed = hashlib.sha256(f"{route_id}:hop:{idx}".encode()).hexdigest()
            ephemeral_relay = f"So1Relay{idx}{relay_seed[:35]}"
            hops.append(
                HopStep(
                    hop_index=idx,
                    ephemeral_relay=ephemeral_relay,
                    delay_ms=idx * 400,
                    amount_usdc=principal_usdc,
                )
            )
            tx_sig = hashlib.sha256(f"{route_id}:tx:{idx}:{principal_usdc}".encode()).hexdigest()
            tx_signatures.append(f"5MH{tx_sig[:85]}")

        receipt = RoutedSettlementReceipt(
            route_id=route_id,
            integration_id=self.integration_id,
            sender=sender,
            token_mint=token_mint,
            mode=mode,
            principal_usdc=principal_usdc,
            full_fee_bps=fee_bps,
            total_fee_usdc=total_fee_usdc,
            partner_revenue_usdc=partner_revenue_usdc,
            pool_contribution_usdc=pool_contribution_usdc,
            qualifying_volume_usdc=qualifying_volume_usdc,
            hops=hops,
            recipients=recipients,
            trm_checks=trm_checks,
            tx_signatures=tx_signatures,
        )
        self._executed_routes[route_id] = receipt
        return receipt
