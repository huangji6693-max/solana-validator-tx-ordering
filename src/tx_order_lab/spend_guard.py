"""Strict fee spend cap guard (0.05 SOL = 50,000,000 lamports) and key isolation enforcer."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

DEFAULT_MAX_SPEND_LAMPORTS = 50_000_000  # 0.05 SOL hard ceiling
ABSOLUTE_CEILING_LAMPORTS = 50_000_000   # Never exceed 0.05 SOL in automated probes

ALPHABET = b"123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    chars = []
    while n > 0:
        n, rem = divmod(n, 58)
        chars.append(ALPHABET[rem:rem + 1])
    pad = 0
    for b in raw:
        if b == 0:
            pad += 1
        else:
            break
    return (b"1" * pad + b"".join(reversed(chars))).decode("ascii")


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s.encode("ascii"):
        idx = ALPHABET.find(bytes([ch]))
        if idx < 0:
            raise ValueError(f"Invalid base58 character: {chr(ch)}")
        n = n * 58 + idx
    res = n.to_bytes((n.bit_length() + 7) // 8, "big") if n > 0 else b""
    pad = 0
    for ch in s:
        if ch == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + res


class SpendCapExceededError(RuntimeError):
    """Raised before broadcasting a transaction if its fee would exceed the spend cap."""


class KeySecurityError(RuntimeError):
    """Raised if a keypair is missing in live mode or located inside the repository tree."""


@dataclass(frozen=True)
class SignerIdentity:
    private_key: Ed25519PrivateKey
    pubkey_bytes: bytes
    pubkey_base58: str
    is_ephemeral_dry_run: bool
    source: str

    def sign(self, message_bytes: bytes) -> bytes:
        return self.private_key.sign(message_bytes)


def _is_subpath(target: Path, repo_root: Path) -> bool:
    try:
        target.resolve().relative_to(repo_root.resolve())
        return True
    except ValueError:
        return False


def load_signer_keypair(
    live_mode: bool = False,
    repo_root: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
) -> SignerIdentity:
    """
    Load Ed25519 keypair strictly from environment variable or external mounted volume.
    Refuses any key file located inside the repository root directory.
    In dry-run mode (live_mode=False), generates an ephemeral in-memory keypair if none is configured.
    """
    env_map = env if env is not None else dict(os.environ)
    root = (repo_root or Path(__file__).resolve().parents[2]).resolve()

    raw_secret = (env_map.get("SOLANA_PRIVATE_KEY") or "").strip()
    key_path_str = (env_map.get("SOLANA_KEYPAIR_PATH") or "").strip()

    if key_path_str:
        key_path = Path(key_path_str).expanduser()
        if _is_subpath(key_path, root):
            raise KeySecurityError(
                f"Refusing to load keypair from inside repository tree: {key_path.resolve()} (repo root: {root})"
            )
        if not key_path.exists():
            if live_mode:
                raise KeySecurityError(f"SOLANA_KEYPAIR_PATH does not exist: {key_path}")
        else:
            raw_secret = key_path.read_text(encoding="utf-8").strip()
            return _parse_secret_material(raw_secret, is_ephemeral=False, source=f"volume:{key_path}")

    if raw_secret:
        return _parse_secret_material(raw_secret, is_ephemeral=False, source="env:SOLANA_PRIVATE_KEY")

    if live_mode:
        raise KeySecurityError(
            "Live mode requires SOLANA_PRIVATE_KEY or external SOLANA_KEYPAIR_PATH; no key material provided."
        )

    # Deterministic or random ephemeral keypair for dry-run mode only
    priv = Ed25519PrivateKey.from_private_bytes(b"\x11" * 32)
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return SignerIdentity(
        private_key=priv,
        pubkey_bytes=pub_bytes,
        pubkey_base58=b58encode(pub_bytes),
        is_ephemeral_dry_run=True,
        source="ephemeral:dry-run",
    )


def _parse_secret_material(raw_secret: str, is_ephemeral: bool, source: str) -> SignerIdentity:
    if raw_secret.startswith("["):
        arr = json.loads(raw_secret)
        if not isinstance(arr, list) or len(arr) not in (32, 64):
            raise KeySecurityError(f"Invalid JSON keypair byte length ({len(arr) if isinstance(arr, list) else 'non-list'})")
        seed = bytes(arr[:32])
    else:
        decoded = b58decode(raw_secret)
        if len(decoded) not in (32, 64):
            raise KeySecurityError(f"Invalid base58 keypair byte length: {len(decoded)}")
        seed = decoded[:32]

    priv = Ed25519PrivateKey.from_private_bytes(seed)
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return SignerIdentity(
        private_key=priv,
        pubkey_bytes=pub_bytes,
        pubkey_base58=b58encode(pub_bytes),
        is_ephemeral_dry_run=is_ephemeral,
        source=source,
    )


class SpendCapGuard:
    """
    Thread-safe atomic fee spend accumulator enforcing the 0.05 SOL (50,000,000 lamports) ceiling.
    Every transaction must reserve its worst-case fee (base_fee + priority_fee) BEFORE transmission.
    """

    def __init__(self, max_spend_lamports: int = DEFAULT_MAX_SPEND_LAMPORTS) -> None:
        if max_spend_lamports <= 0:
            raise ValueError("max_spend_lamports must be positive")
        if max_spend_lamports > ABSOLUTE_CEILING_LAMPORTS:
            raise SpendCapExceededError(
                f"Configured max_spend_lamports ({max_spend_lamports}) exceeds hard 0.05 SOL protocol ceiling ({ABSOLUTE_CEILING_LAMPORTS})"
            )
        self._max_spend_lamports = int(max_spend_lamports)
        self._spent_lamports = 0
        self._tx_count = 0
        self._ledger: list[dict[str, int | str]] = []
        self._lock = threading.Lock()

    @property
    def max_spend_lamports(self) -> int:
        return self._max_spend_lamports

    @property
    def spent_lamports(self) -> int:
        with self._lock:
            return self._spent_lamports

    @property
    def remaining_lamports(self) -> int:
        with self._lock:
            return self._max_spend_lamports - self._spent_lamports

    @property
    def tx_count(self) -> int:
        with self._lock:
            return self._tx_count

    def reserve_and_record(
        self,
        signature: str,
        base_fee_lamports: int,
        priority_fee_lamports: int,
        slot_target: int,
    ) -> int:
        """
        Atomically check and charge (base_fee_lamports + priority_fee_lamports) against the cap.
        Raises SpendCapExceededError prior to network broadcast if the cap would be breached.
        """
        if base_fee_lamports < 5000 or priority_fee_lamports < 0:
            raise ValueError("Invalid fee parameters: base_fee_lamports >= 5000 and priority_fee_lamports >= 0 required")
        total_fee = int(base_fee_lamports + priority_fee_lamports)

        with self._lock:
            projected = self._spent_lamports + total_fee
            if projected > self._max_spend_lamports:
                raise SpendCapExceededError(
                    f"Spend cap breached: projected {projected} lamports > cap {self._max_spend_lamports} lamports "
                    f"(tx={signature[:16]}..., fee={total_fee} lamports)"
                )
            self._spent_lamports = projected
            self._tx_count += 1
            self._ledger.append({
                "seq": self._tx_count,
                "signature": signature,
                "slot_target": slot_target,
                "base_fee_lamports": base_fee_lamports,
                "priority_fee_lamports": priority_fee_lamports,
                "total_fee_lamports": total_fee,
                "cumulative_spent_lamports": self._spent_lamports,
            })
            return self._spent_lamports

    def summary(self) -> dict:
        with self._lock:
            return {
                "max_spend_lamports": self._max_spend_lamports,
                "max_spend_sol": round(self._max_spend_lamports / 1e9, 6),
                "spent_lamports": self._spent_lamports,
                "spent_sol": round(self._spent_lamports / 1e9, 6),
                "remaining_lamports": self._max_spend_lamports - self._spent_lamports,
                "utilization_pct": round((self._spent_lamports / self._max_spend_lamports) * 100.0, 4),
                "transactions_charged": self._tx_count,
                "ledger": list(self._ledger),
            }
