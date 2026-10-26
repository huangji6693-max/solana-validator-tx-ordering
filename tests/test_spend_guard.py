"""Unit tests for 0.05 SOL SpendCapGuard and strict key isolation (compatible with unittest and pytest)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tx_order_lab.spend_guard import (
    DEFAULT_MAX_SPEND_LAMPORTS,
    KeySecurityError,
    SpendCapExceededError,
    SpendCapGuard,
    b58encode,
    load_signer_keypair,
)


class TestSpendGuardAndKeys(unittest.TestCase):
    def test_spend_cap_rejects_ceiling_above_005_sol(self) -> None:
        with self.assertRaisesRegex(SpendCapExceededError, "exceeds hard 0.05 SOL"):
            SpendCapGuard(max_spend_lamports=DEFAULT_MAX_SPEND_LAMPORTS + 1)

    def test_spend_cap_allows_within_budget_and_blocks_overflow(self) -> None:
        guard = SpendCapGuard(max_spend_lamports=20_000)
        spent_1 = guard.reserve_and_record(
            "sig1" * 16, base_fee_lamports=5000, priority_fee_lamports=4000, slot_target=100
        )
        self.assertEqual(spent_1, 9000)
        self.assertEqual(guard.remaining_lamports, 11_000)

        spent_2 = guard.reserve_and_record(
            "sig2" * 16, base_fee_lamports=5000, priority_fee_lamports=6000, slot_target=100
        )
        self.assertEqual(spent_2, 20_000)
        self.assertEqual(guard.remaining_lamports, 0)

        with self.assertRaisesRegex(SpendCapExceededError, "Spend cap breached"):
            guard.reserve_and_record(
                "sig3" * 16, base_fee_lamports=5000, priority_fee_lamports=0, slot_target=100
            )
        self.assertEqual(guard.spent_lamports, 20_000)
        self.assertEqual(guard.tx_count, 2)

    def test_key_loader_rejects_key_inside_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp) / "repo"
            repo_root.mkdir()
            insider_key = repo_root / "id.json"
            insider_key.write_text(str(list(range(64))), encoding="utf-8")

            with self.assertRaisesRegex(
                KeySecurityError, "Refusing to load keypair from inside repository tree"
            ):
                load_signer_keypair(
                    live_mode=False,
                    repo_root=repo_root,
                    env={"SOLANA_KEYPAIR_PATH": str(insider_key)},
                )

    def test_key_loader_rejects_live_mode_without_external_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp) / "repo"
            repo_root.mkdir()
            with self.assertRaisesRegex(KeySecurityError, "Live mode requires SOLANA_PRIVATE_KEY"):
                load_signer_keypair(live_mode=True, repo_root=repo_root, env={})

    def test_key_loader_accepts_external_volume_and_env_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp) / "repo"
            repo_root.mkdir()
            ext_secrets = Path(tmp) / "secrets"
            ext_secrets.mkdir()
            key_file = ext_secrets / "solana-keypair.json"
            key_file.write_text(str([7] * 64), encoding="utf-8")

            signer_vol = load_signer_keypair(
                live_mode=True,
                repo_root=repo_root,
                env={"SOLANA_KEYPAIR_PATH": str(key_file)},
            )
            self.assertFalse(signer_vol.is_ephemeral_dry_run)
            self.assertTrue(signer_vol.source.startswith("volume:"))

            signer_env = load_signer_keypair(
                live_mode=True,
                repo_root=repo_root,
                env={"SOLANA_PRIVATE_KEY": b58encode(bytes([7] * 32))},
            )
            self.assertEqual(signer_env.pubkey_base58, signer_vol.pubkey_base58)


if __name__ == "__main__":
    unittest.main()
