"""Unit tests for deterministic Solana probe transaction builder (compatible with unittest and pytest)."""

from __future__ import annotations

import unittest

from tx_order_lab.probe_builder import build_probe_burst
from tx_order_lab.spend_guard import SpendCapGuard, b58encode, load_signer_keypair


class TestProbeBuilder(unittest.TestCase):
    def test_build_probe_burst_modes(self) -> None:
        signer = load_signer_keypair(live_mode=False, env={})
        guard = SpendCapGuard()
        blockhash = b58encode(bytes([42] * 32))

        contended = build_probe_burst(
            signer=signer,
            spend_guard=guard,
            recent_blockhash_b58=blockhash,
            target_slot=461701391,
            validator_identity="HEL1USMZKAL2odpNBj2oCjffnFGaYwmbGmyewGv1e2TU",
            client_version="4.3.2",
            mode="REVERSE_FEE_CONTENDED",
            burst_size=5,
        )
        self.assertEqual(len(contended), 5)
        shared_locks = {p.shared_writable_account for p in contended}
        self.assertEqual(len(shared_locks), 1)
        prices = [p.compute_unit_price_micro_lamports for p in contended]
        self.assertEqual(prices, sorted(prices))
        self.assertEqual(len(set(prices)), 5)

        disjoint = build_probe_burst(
            signer=signer,
            spend_guard=guard,
            recent_blockhash_b58=blockhash,
            target_slot=461701395,
            validator_identity="9eGrDohdNTAo61DRHyfMuqKWXqYnA3i254Wiszxe8FoY",
            client_version="26.10.4",
            mode="DISJOINT_PARALLEL_LADDER",
            burst_size=5,
        )
        self.assertEqual(len({p.shared_writable_account for p in disjoint}), 5)

        ties = build_probe_burst(
            signer=signer,
            spend_guard=guard,
            recent_blockhash_b58=blockhash,
            target_slot=461696595,
            validator_identity="AHZxzLeRGRfNVFrCmP58iJgEwbcXyZeAkZ32CmbfEmYR",
            client_version="0.1.1",
            mode="EQUAL_FEE_TIE_BREAKER",
            burst_size=5,
        )
        self.assertEqual(len({p.compute_unit_price_micro_lamports for p in ties}), 1)
        self.assertEqual(len({p.signature for p in ties}), 5)


if __name__ == "__main__":
    unittest.main()
