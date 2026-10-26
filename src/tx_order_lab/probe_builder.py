"""Deterministic Solana probe transaction builder for testing validator scheduler rules."""

from __future__ import annotations

import hashlib
import math
import struct
from dataclasses import dataclass
from typing import Literal

from .spend_guard import SignerIdentity, SpendCapGuard, b58decode, b58encode

COMPUTE_BUDGET_PROGRAM_ID = b58decode("ComputeBudget111111111111111111111111111111")
MEMO_PROGRAM_ID = b58decode("MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr")
SYSTEM_PROGRAM_ID = b"\x00" * 32

ProbeMode = Literal[
    "REVERSE_FEE_CONTENDED",     # Mode A: Sent lowest-fee first -> highest-fee last, sharing a writable account lock
    "DISJOINT_PARALLEL_LADDER",  # Mode B: Disjoint writable accounts across threads with priority fee ladder
    "EQUAL_FEE_TIE_BREAKER",     # Mode C: Identical priority fee & CU limit to isolate FIFO vs hash tie-breaking
]


def _encode_compact_u16(val: int) -> bytes:
    out = bytearray()
    rem = val
    while True:
        elem = rem & 0x7F
        rem >>= 7
        if rem == 0:
            out.append(elem)
            break
        out.append(elem | 0x80)
    return bytes(out)


def encode_set_compute_unit_limit(units: int) -> bytes:
    """ComputeBudgetInstruction::SetComputeUnitLimit (tag = 0x02, u32 LE)."""
    return b"\x02" + struct.pack("<I", int(units))


def encode_set_compute_unit_price(micro_lamports: int) -> bytes:
    """ComputeBudgetInstruction::SetComputeUnitPrice (tag = 0x03, u64 LE)."""
    return b"\x03" + struct.pack("<Q", int(micro_lamports))


def encode_system_transfer(lamports: int) -> bytes:
    """SystemInstruction::Transfer (tag = 2 u32 LE, lamports u64 LE)."""
    return struct.pack("<IQ", 2, int(lamports))


@dataclass(frozen=True)
class ProbeTransaction:
    send_sequence: int
    mode: ProbeMode
    target_slot: int
    validator_identity: str
    client_version: str
    signature: str
    wire_base64_or_hex: str
    compute_unit_limit: int
    compute_unit_price_micro_lamports: int
    base_fee_lamports: int
    priority_fee_lamports: int
    total_fee_lamports: int
    estimated_cost_units: int
    expected_scheduler_priority_score: float
    shared_writable_account: str
    memo_tag: str


def derive_probe_writable_account(seed_tag: str) -> bytes:
    """Derive a deterministic 32-byte writable scratch account address for probe isolation."""
    return hashlib.sha256(f"tx-order-lab:{seed_tag}".encode("utf-8")).digest()


def build_signed_probe_transaction(
    signer: SignerIdentity,
    recent_blockhash_b58: str,
    send_sequence: int,
    mode: ProbeMode,
    target_slot: int,
    validator_identity: str,
    client_version: str,
    compute_unit_limit: int,
    compute_unit_price_micro_lamports: int,
    shared_writable_pubkey_bytes: bytes,
) -> ProbeTransaction:
    """
    Construct and Ed25519-sign a canonical Solana transaction containing:
      1. ComputeBudget::SetComputeUnitLimit(compute_unit_limit)
      2. ComputeBudget::SetComputeUnitPrice(compute_unit_price_micro_lamports)
      3. SystemProgram::Transfer(1 lamport) touching shared_writable_pubkey_bytes (writable)
      4. MemoProgram::Memo("probe:<slot>:<mode>:seq=<seq>:price=<price>")
    """
    blockhash_bytes = b58decode(recent_blockhash_b58)
    if len(blockhash_bytes) != 32:
        raise ValueError(f"Invalid recentBlockhash length: {len(blockhash_bytes)}")

    memo_str = f"probe:{target_slot}:{mode}:seq={send_sequence:02d}:cu_price={compute_unit_price_micro_lamports}"
    memo_bytes = memo_str.encode("utf-8")

    # Account keys layout:
    # [0] signer (writable, signer)
    # [1] shared_writable_pubkey_bytes (writable, non-signer)
    # [2] COMPUTE_BUDGET_PROGRAM_ID (readonly, non-signer)
    # [3] SYSTEM_PROGRAM_ID (readonly, non-signer)
    # [4] MEMO_PROGRAM_ID (readonly, non-signer)
    account_keys = [
        signer.pubkey_bytes,
        shared_writable_pubkey_bytes,
        COMPUTE_BUDGET_PROGRAM_ID,
        SYSTEM_PROGRAM_ID,
        MEMO_PROGRAM_ID,
    ]
    header = bytes([
        1,  # numRequiredSignatures
        0,  # numReadonlySignedAccounts
        3,  # numReadonlyUnsignedAccounts (ComputeBudget, System, Memo)
    ])

    ix_cu_limit = encode_set_compute_unit_limit(compute_unit_limit)
    ix_cu_price = encode_set_compute_unit_price(compute_unit_price_micro_lamports)
    ix_transfer = encode_system_transfer(1)

    # Instructions: (program_id_index, account_indices, data)
    compiled_ixs = [
        (2, b"", ix_cu_limit),
        (2, b"", ix_cu_price),
        (3, bytes([0, 1]), ix_transfer),
        (4, bytes([0]), memo_bytes),
    ]

    msg_buf = bytearray()
    msg_buf.extend(header)
    msg_buf.extend(_encode_compact_u16(len(account_keys)))
    for k in account_keys:
        msg_buf.extend(k)
    msg_buf.extend(blockhash_bytes)
    msg_buf.extend(_encode_compact_u16(len(compiled_ixs)))
    for prog_idx, acct_idxs, data in compiled_ixs:
        msg_buf.append(prog_idx)
        msg_buf.extend(_encode_compact_u16(len(acct_idxs)))
        msg_buf.extend(acct_idxs)
        msg_buf.extend(_encode_compact_u16(len(data)))
        msg_buf.extend(data)

    message_bytes = bytes(msg_buf)
    sig_bytes = signer.sign(message_bytes)
    sig_b58 = b58encode(sig_bytes)

    wire_tx = _encode_compact_u16(1) + sig_bytes + message_bytes

    base_fee_lamports = 5000
    priority_fee_lamports = math.ceil((compute_unit_limit * compute_unit_price_micro_lamports) / 1_000_000)
    total_fee_lamports = base_fee_lamports + priority_fee_lamports

    # Agave CostModel overhead: signature_cost (720) + write_lock_cost (300 * 2) + data_bytes_cost + cu_limit
    estimated_cost_units = 720 + 600 + 180 + compute_unit_limit
    expected_scheduler_priority_score = round((total_fee_lamports * 1_000_000.0) / estimated_cost_units, 4)

    return ProbeTransaction(
        send_sequence=send_sequence,
        mode=mode,
        target_slot=target_slot,
        validator_identity=validator_identity,
        client_version=client_version,
        signature=sig_b58,
        wire_base64_or_hex=wire_tx.hex(),
        compute_unit_limit=compute_unit_limit,
        compute_unit_price_micro_lamports=compute_unit_price_micro_lamports,
        base_fee_lamports=base_fee_lamports,
        priority_fee_lamports=priority_fee_lamports,
        total_fee_lamports=total_fee_lamports,
        estimated_cost_units=estimated_cost_units,
        expected_scheduler_priority_score=expected_scheduler_priority_score,
        shared_writable_account=b58encode(shared_writable_pubkey_bytes),
        memo_tag=memo_str,
    )


def build_probe_burst(
    signer: SignerIdentity,
    spend_guard: SpendCapGuard,
    recent_blockhash_b58: str,
    target_slot: int,
    validator_identity: str,
    client_version: str,
    mode: ProbeMode = "REVERSE_FEE_CONTENDED",
    burst_size: int = 6,
    compute_unit_limit: int = 5_000,
) -> list[ProbeTransaction]:
    """
    Build a complete K-transaction probe burst and atomically reserve fees via SpendCapGuard.
    - REVERSE_FEE_CONTENDED: Sent in order seq=1..K with ASCENDING priority fees (so seq=1 has lowest fee
      and seq=K has highest fee), all write-locking the SAME scratch account. If the validator orders by
      priority fee rather than arrival order (FIFO), landing order in the block will invert send_sequence!
    - DISJOINT_PARALLEL_LADDER: Sent in order seq=1..K with ascending priority fees, each write-locking
      a DISJOINT scratch account so BankingStage workers can schedule them in parallel.
    - EQUAL_FEE_TIE_BREAKER: Sent in order seq=1..K with identical priority fees (50,000 micro-lamports/CU)
      to isolate tie-breaking rules (FIFO arrival vs signature ordering).
    """
    fee_ladder_micro_lamports = [
        10_000 * (i + 1) for i in range(burst_size)
    ]  # e.g. 10k, 20k, 30k, 40k, 50k, 60k micro-lamports/CU

    shared_lock = derive_probe_writable_account(f"contended:{target_slot}:{validator_identity[:8]}")
    burst: list[ProbeTransaction] = []

    for idx in range(burst_size):
        seq = idx + 1
        if mode == "REVERSE_FEE_CONTENDED":
            cu_price = fee_ladder_micro_lamports[idx]  # seq 1 = lowest fee (sent first), seq K = highest fee (sent last)
            writable_target = shared_lock
        elif mode == "DISJOINT_PARALLEL_LADDER":
            cu_price = fee_ladder_micro_lamports[idx]
            writable_target = derive_probe_writable_account(f"disjoint:{target_slot}:seq={seq}")
        elif mode == "EQUAL_FEE_TIE_BREAKER":
            cu_price = 50_000
            writable_target = shared_lock
        else:
            raise ValueError(f"Unsupported probe mode: {mode}")

        probe_tx = build_signed_probe_transaction(
            signer=signer,
            recent_blockhash_b58=recent_blockhash_b58,
            send_sequence=seq,
            mode=mode,
            target_slot=target_slot,
            validator_identity=validator_identity,
            client_version=client_version,
            compute_unit_limit=compute_unit_limit,
            compute_unit_price_micro_lamports=cu_price,
            shared_writable_pubkey_bytes=writable_target,
        )
        # Enforce hard 0.05 SOL spend cap BEFORE adding to dispatch queue
        spend_guard.reserve_and_record(
            signature=probe_tx.signature,
            base_fee_lamports=probe_tx.base_fee_lamports,
            priority_fee_lamports=probe_tx.priority_fee_lamports,
            slot_target=target_slot,
        )
        burst.append(probe_tx)

    return burst
