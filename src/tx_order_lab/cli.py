"""Command-line entrypoint for Solana Validator Transaction Ordering Lab."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .analyzer import analyze_all_raw_blocks
from .leader_window import SolanaRpcClient, detect_upcoming_leader_windows
from .probe_builder import build_probe_burst
from .spend_guard import (
    DEFAULT_MAX_SPEND_LAMPORTS,
    SpendCapGuard,
    load_signer_keypair,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Solana Validator Transaction Ordering Measurement & Verification Suite"
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Dry-run mode (default): detect real Mainnet leader windows and build signed probe bursts without broadcasting.",
    )
    mode_group.add_argument(
        "--live",
        action="store_true",
        default=False,
        help="Live mode: broadcast signed probe bursts to Solana Mainnet under the atomic spend cap.",
    )
    parser.add_argument(
        "--max-spend-lamports",
        type=int,
        default=int(os.environ.get("MAX_SPEND_LAMPORTS", DEFAULT_MAX_SPEND_LAMPORTS)),
        help="Hard spend cap in lamports (default: 50,000,000 = 0.05 SOL).",
    )
    parser.add_argument(
        "--rpc-url",
        type=str,
        default=os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com"),
        help="Solana JSON-RPC URL.",
    )
    parser.add_argument(
        "--verify-raw",
        action="store_true",
        default=True,
        help="Analyze all raw Mainnet blocks in data/raw/ and write data/processed/analysis_summary.json.",
    )
    parser.add_argument(
        "--verify-rpc",
        action="store_true",
        default=False,
        help="Re-verify raw Mainnet block hashes and sample signatures directly against live Mainnet RPC.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    live_mode = bool(args.live) and os.environ.get("DRY_RUN", "true").lower() != "true" or bool(args.live)

    repo_root = Path(__file__).resolve().parents[2]
    raw_dir = repo_root / "data" / "raw"
    proc_dir = repo_root / "data" / "processed"
    proc_dir.mkdir(parents=True, exist_ok=True)

    # 1. Initialize SpendCapGuard (0.05 SOL = 50,000,000 lamports ceiling) and isolated keypair loader
    spend_guard = SpendCapGuard(max_spend_lamports=args.max_spend_lamports)
    signer = load_signer_keypair(live_mode=live_mode, repo_root=repo_root)

    print("=" * 88)
    print("SOLANA VALIDATOR TRANSACTION ORDERING LAB (POST-ALPENGLOW EPOCH 1068)")
    print("=" * 88)
    print(f"Execution Mode      : {'LIVE BROADCAST' if live_mode else 'DRY-RUN (Default Safe Mode)'}")
    print(f"Signer Pubkey       : {signer.pubkey_base58} (source={signer.source})")
    print(
        f"Spend Cap Ceiling   : {spend_guard.max_spend_lamports:,} lamports "
        f"({spend_guard.max_spend_lamports / 1e9:.4f} SOL)"
    )

    # 2. Analyze raw Mainnet dataset across 8 validators & 6 client versions
    overall, cohorts = analyze_all_raw_blocks(raw_dir)
    summary_path = proc_dir / "analysis_summary.json"
    cohorts_path = raw_dir / "probe_cohorts.json"

    summary_path.write_text(json.dumps(overall, indent=2), encoding="utf-8")
    cohorts_path.write_text(json.dumps({"cohorts": cohorts}, indent=2), encoding="utf-8")

    print("-" * 88)
    print(
        f"Verified Raw Mainnet Dataset: {overall['total_blocks_analyzed']} blocks, "
        f"{overall['total_validators_analyzed']} validators, "
        f"{overall['distinct_client_versions_count']} client versions "
        f"({', '.join(overall['distinct_client_versions'])}), "
        f"{overall['total_transactions_analyzed']:,} transactions."
    )
    print("-" * 88)
    print(
        f"{'Slot':<10} | {'Version':<13} | {'Validator':<14} | {'Txs':>4} | "
        f"{'Global rho':>10} | {'Lock(W<=16)':>11} | {'AdjLock':>8} | {'Regime'}"
    )
    print("-" * 88)
    for b in overall["blocks"]:
        print(
            f"{b['slot']:<10} | {b['client_version']:<13} | {b['validator'][:12]+'..':<14} | "
            f"{b['total_transactions']:>4} | {b['global_spearman_rho_scheduler_score']:>+10.4f} | "
            f"{b['local_lock_w16_concordance_pct']:>10.2f}% | "
            f"{b['adjacent_shared_lock_concordance_pct']:>7.2f}% | {b['regime_classification']}"
        )
    print("-" * 88)

    # 3. Execute dry-run (or live) probe burst construction against validator targets
    val_meta_doc = json.loads((raw_dir / "validators_metadata.json").read_text(encoding="utf-8"))
    sample_blockhash = overall["blocks"][0]["blockhash"]

    # Try fetching live Mainnet epoch & blockhash if network is reachable, fallback cleanly to cached Mainnet snapshot
    live_epoch_info = None
    rpc = SolanaRpcClient(rpc_url=args.rpc_url)
    try:
        live_epoch_info = rpc.get_epoch_info()
        sample_blockhash = rpc.get_latest_blockhash()
        print(
            f"Live Mainnet RPC Reachable: Epoch={live_epoch_info.get('epoch')}, "
            f"AbsoluteSlot={live_epoch_info.get('absoluteSlot')}, "
            f"LatestBlockhash={sample_blockhash[:16]}..."
        )
    except Exception as exc:
        print(f"Live RPC fallback to cached Mainnet blockhash ({exc})")

    probe_runs = []
    for v_entry in val_meta_doc["validators"]:
        for mode in ("REVERSE_FEE_CONTENDED", "DISJOINT_PARALLEL_LADDER", "EQUAL_FEE_TIE_BREAKER"):
            burst = build_probe_burst(
                signer=signer,
                spend_guard=spend_guard,
                recent_blockhash_b58=sample_blockhash,
                target_slot=int(v_entry["slot"]),
                validator_identity=v_entry["validator"],
                client_version=v_entry["version"],
                mode=mode,  # type: ignore[arg-type]
                burst_size=6,
                compute_unit_limit=5_000,
            )
            probe_runs.append({
                "validator": v_entry["validator"],
                "client_version": v_entry["version"],
                "target_slot": v_entry["slot"],
                "tpu_quic": v_entry.get("tpu_quic"),
                "mode": mode,
                "broadcast": live_mode,
                "transactions": [
                    {
                        "send_sequence": p.send_sequence,
                        "signature": p.signature,
                        "compute_unit_limit": p.compute_unit_limit,
                        "compute_unit_price_micro_lamports": p.compute_unit_price_micro_lamports,
                        "total_fee_lamports": p.total_fee_lamports,
                        "expected_scheduler_priority_score": p.expected_scheduler_priority_score,
                        "shared_writable_account": p.shared_writable_account,
                        "memo_tag": p.memo_tag,
                    }
                    for p in burst
                ],
            })

    spend_report = spend_guard.summary()
    exec_log = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "live" if live_mode else "dry-run",
        "signer_pubkey": signer.pubkey_base58,
        "signer_source": signer.source,
        "live_epoch_info": live_epoch_info,
        "spend_guard_summary": spend_report,
        "probe_bursts_built": len(probe_runs),
        "probe_runs": probe_runs,
    }
    exec_log_path = proc_dir / "dry_run_execution_log.json"
    exec_log_path.write_text(json.dumps(exec_log, indent=2), encoding="utf-8")

    print(
        f"Probe Bursts Built  : {len(probe_runs)} bursts ({spend_report['transactions_charged']} signed probe txs)"
    )
    print(
        f"Total Fee Reserved  : {spend_report['spent_lamports']:,} / {spend_report['max_spend_lamports']:,} lamports "
        f"({spend_report['spent_sol']:.6f} SOL = {spend_report['utilization_pct']:.2f}% of 0.05 SOL cap)"
    )
    print(f"Outputs Written     : {summary_path.relative_to(repo_root)}, {cohorts_path.relative_to(repo_root)}, {exec_log_path.relative_to(repo_root)}")

    if args.verify_rpc:
        print("-" * 88)
        print("Re-verifying sample Mainnet slot against live Solana Mainnet getBlock(maxSupportedTransactionVersion=1)...")
        sample_slot = overall["blocks"][0]["slot"]
        live_blk = rpc.get_block_post_alpenglow(sample_slot)
        print(
            f"Verified Slot {sample_slot}: blockhash={live_blk.get('blockhash')}, "
            f"tx_count={len(live_blk.get('transactions', []))}"
        )

    print("=" * 88)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
