import unittest
from multihopper_router import (
    MultiHopperRouter,
    RecipientAllocation,
    RouteMode,
    calculate_funded_prize_pool,
    allocate_top_three_prizes,
    evaluate_product_economics,
)


class TestMultiHopperRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.router = MultiHopperRouter(
            integration_id="mh_sol_agent_treasury_01",
            webhook_secret="test_whsec_secret",
        )
        self.valid_sender = "AyXYaA9Nf4z5fpLKY6DmubWe6D2qveMd79w8pEDNHcDw"
        self.valid_recipient_1 = "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU"
        self.valid_recipient_2 = "9xQeWvG816bUx9EPjHmaT23yvVM2ZWbrrpZb9PusVFin"

    def test_multi_send_principal_counted_once_and_revenue_split(self) -> None:
        receipt = self.router.execute_routed_settlement(
            sender=self.valid_sender,
            recipients=[
                RecipientAllocation(self.valid_recipient_1, 60_000.0, "Invoice #101"),
                RecipientAllocation(self.valid_recipient_2, 40_000.0, "Invoice #102"),
            ],
            mode=RouteMode.MULTI_SEND,
            num_hops=3,
        )
        # Principal is $100,000 even across 3 hops and 2 recipients
        self.assertEqual(receipt.principal_usdc, 100_000.0)
        # 0.50% full fee = $500; partner gets 0.25% ($250), pool gets 0.25% ($250)
        self.assertEqual(receipt.total_fee_usdc, 500.0)
        self.assertEqual(receipt.partner_revenue_usdc, 250.0)
        self.assertEqual(receipt.pool_contribution_usdc, 250.0)
        self.assertEqual(receipt.qualifying_volume_usdc, 100_000.0)
        self.assertEqual(len(receipt.hops), 3)

    def test_discounted_fee_scales_qualifying_volume_proportionally(self) -> None:
        receipt = self.router.execute_routed_settlement(
            sender=self.valid_sender,
            recipients=[RecipientAllocation(self.valid_recipient_1, 200_000.0)],
            fee_bps=25,  # half-rate discount
        )
        self.assertEqual(receipt.qualifying_volume_usdc, 100_000.0)

    def test_devnet_volume_excluded_from_qualifying_volume(self) -> None:
        receipt = self.router.execute_routed_settlement(
            sender=self.valid_sender,
            recipients=[RecipientAllocation(self.valid_recipient_1, 500_000.0)],
            is_devnet=True,
        )
        self.assertEqual(receipt.qualifying_volume_usdc, 0.0)

    def test_trm_compliance_blocks_sanctioned_recipient(self) -> None:
        with self.assertRaises(PermissionError):
            self.router.execute_routed_settlement(
                sender=self.valid_sender,
                recipients=[
                    RecipientAllocation("OFACSanctionedWallet111111111111111111111111", 10_000.0)
                ],
            )

    def test_circular_self_transfer_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.router.execute_routed_settlement(
                sender=self.valid_sender,
                recipients=[RecipientAllocation(self.valid_sender, 10_000.0)],
            )

    def test_signed_completion_webhook_verification(self) -> None:
        payload = b'{"route_id":"route_123","status":"COMPLETED"}'
        sig = self.router.sign_completion_webhook(payload)
        self.assertTrue(self.router.verify_completion_webhook(payload, sig))
        self.assertFalse(self.router.verify_completion_webhook(payload, "00" * 32))

    def test_prize_pool_unlock_schedule_and_proportional_allocation(self) -> None:
        self.assertEqual(calculate_funded_prize_pool(1_500_000), 0.0)
        self.assertEqual(calculate_funded_prize_pool(2_000_000), 5_000.0)
        self.assertEqual(calculate_funded_prize_pool(4_000_000), 10_000.0)
        self.assertEqual(calculate_funded_prize_pool(8_000_000), 20_000.0)
        self.assertEqual(calculate_funded_prize_pool(11_000_000), 27_000.0)
        self.assertEqual(calculate_funded_prize_pool(20_000_000), 50_000.0)

        summary = evaluate_product_economics(
            product_qualifying_volume_usd=4_000_000.0,
            other_top_competitors_volume_usd=[3_500_000.0, 2_500_000.0, 50_000.0],
            aggregate_campaign_volume_usd=11_000_000.0,
        )
        # At $11M aggregate volume, pool is $27,000; top 3 have $10M combined, our share is 40% = $10,800
        # Plus 0.25% partner fee on $4M = $10,000 -> total $20,800
        self.assertEqual(summary.funded_prize_pool_usd, 27_000.0)
        self.assertEqual(summary.partner_direct_revenue_usd, 10_000.0)
        self.assertEqual(summary.estimated_prize_award_usd, 10_800.0)
        self.assertEqual(summary.total_partner_earnings_usd, 20_800.0)


if __name__ == "__main__":
    unittest.main()
