# Inside the Block: How Solana Validators Order Transactions (Post-Alpenglow Measurement Suite)

 Empirical measurement, probe transaction generator, and statistical verification suite investigating how Solana Mainnet validators across **6 distinct client software/fork versions** (`4.3.2`, `26.10.4`, `26.10.3`, `4.4.0-rc.0`, `4.5.0-alpha.2`, and `0.1.1`) order transactions inside a block following the **October 21, 2026 Alpenglow upgrade** (`Epoch 1068`).

---

## 1. One-Command Reproducibility (Docker Compose)

The entire verification suite—unit tests, key-isolation checks, `0.05 SOL` (`50,000,000 lamports`) spend-cap enforcement, raw Mainnet block analysis across 8 validators (4,601 transactions), and `--dry-run` probe burst construction—runs in a single command:

```bash
docker compose up --build
```

### Local CLI Execution (Without Docker)

```bash
# 1. Run the automated unit & integration test suite (8/8 tests)
PYTHONPATH=src python3 -m unittest discover -s tests -v

# 2. Run the default safe dry-run pipeline and regenerate data/processed/ artifacts
PYTHONPATH=src python3 -m tx_order_lab.cli --dry-run --verify-raw

# 3. Re-verify raw block hashes and transaction counts directly against live Solana Mainnet RPC
PYTHONPATH=src python3 -m tx_order_lab.cli --dry-run --verify-raw --verify-rpc

# 4. Live broadcast mode (strictly gated behind --live, external keypair, and 0.05 SOL spend cap)
SOLANA_KEYPAIR_PATH=/secrets/solana-keypair.json \
  PYTHONPATH=src python3 -m tx_order_lab.cli --live --max-spend-lamports 50000000
```

---

## 2. Experimental Design: Why This Architecture

A naive experiment that sends $K$ transactions with random priority fees and checks whether their landing indices $0..N$ are globally sorted conflates **four distinct physical processes**:
1. **Continuous Proof-of-History (PoH) Entry Streaming**: Solana validators do not buffer an entire 400ms block and sort it at the end of the slot. Instead, `BankingStage` workers (or Firedancer `fd_pack` tiles) continuously pull ready transactions from an in-memory priority queue and commit them to the 64-tick PoH stream every few milliseconds. A low-fee transaction arriving at $t = 30\text{ms}$ is hashed into PoH before a high-fee transaction arriving at $t = 120\text{ms}$ ever reaches the leader.
2. **Account Write-Lock Contention vs. Parallel Thread Dispatch**: Non-conflicting transactions (`Disjoint Writable Accounts`) are dispatched concurrently across multiple banking worker threads (4 non-vote worker threads in standard Agave; parallel banking tiles in Frankendancer/Firedancer). Execution duration variance (`computeUnitsConsumed`) causes fast low-fee transactions on Thread B to finish committing before slow high-fee transactions on Thread A.
3. **Contended Write-Lock Serialization (`PrioGraph` / `fd_pack` Treap)**: When multiple transactions write-lock the **same account** within the same scheduler window, they *cannot* execute in parallel. The scheduler's conflict graph (`PrioGraph` in Agave `CentralScheduler`) chains them sequentially in descending order of scheduler priority:
   $$\text{SchedulerPriority} = \frac{\text{TotalFeeLamports} \times 10^6}{\text{CostUnits}}$$
4. **Post-Alpenglow Transaction Format Heterogeneity (`Version 1` vs `Version 0` / `legacy`)**: Following the October 21, 2026 Alpenglow upgrade, Mainnet blocks contain `Version 1` transactions (`SIMD-0166` `transactionConfig`, where `priorityFee` is specified in flat lamports and `costUnits` is recorded in `meta.costUnits`) alongside `Version 0` and `legacy` transactions (`ComputeBudget::SetComputeUnitPrice` in micro-lamports per CU).

To separate these effects cleanly, `tx_order_lab` implements **three orthogonal probe modes** (`src/tx_order_lab/probe_builder.py`) and a **three-scale statistical decomposition** (`src/tx_order_lab/analyzer.py`):

| Probe Mode / Analysis Layer | Writable Account Lock Topology | Send Sequence vs. Priority Fee | What It Isolates |
| :--- | :--- | :--- | :--- |
| **`Mode A: REVERSE_FEE_CONTENDED`** | **Shared Writable Account** (`SHA256("tx-order-lab:contended:<slot>:<validator>")`) | Sent in sequence `1..K` with **strictly ascending** `computeUnitPrice` (`10k -> 60k` $\mu$lamports/CU) | Forces all $K$ probes into a single `PrioGraph` conflict chain. If the scheduler orders by priority, landing order **inverts** send order (`K..1`). If FIFO, landing order matches send order (`1..K`). |
| **`Mode B: DISJOINT_PARALLEL_LADDER`** | **Disjoint Writable Accounts** (`SHA256("tx-order-lab:disjoint:<slot>:seq=<i>")`) | Sent in sequence `1..K` with ascending `computeUnitPrice` (`10k -> 60k` $\mu$lamports/CU) | Measures cross-thread dispersion when non-conflicting transactions are scheduled across parallel banking workers/tiles. |
| **`Mode C: EQUAL_FEE_TIE_BREAKER`** | **Shared Writable Account** | Sent in sequence `1..K` with **identical** `computeUnitPrice` (`50k` $\mu$lamports/CU) and identical `computeUnitLimit` (`5,000 CU`) | Isolates tie-breaking behavior when `SchedulerPriority` scores are identical (FIFO arrival vs. signature lexicographical order). |

---

## 3. How This Design Handles "What You Will Have to Account For"

### 3.1 Leader Schedule and Leader Types
- `src/tx_order_lab/leader_window.py` queries `getEpochInfo`, `getSlotLeaders`, `getClusterNodes`, and `getVoteAccounts` to group consecutive leader slots into 4-slot rotation windows (`[slot_0, slot_1, slot_2, slot_3]`).
- **Boundary Jitter Avoidance**: Slot `slot_0` suffers from packet forwarding lag during leader handoff from the previous validator, and `slot_3` risks spillover into the next validator's window. Our detector explicitly targets **interior slot `slot_0 + 1`**.
- **Client Diversity**: Across `Epoch 1068` (October 26, 2026 UTC), we captured and analyzed **8 Mainnet validators spanning 6 distinct gossip version strings**:
  1. `4.3.2` — Mainstream Agave / Jito-Agave post-Alpenglow production release (`HEL1USMZKAL2odpNBj2oCjffnFGaYwmbGmyewGv1e2TU` & `Fd7btgySsrjuo25CJCj7oE7VPMyezDhnx7pZkj2v69Nk`)
  2. `26.10.4` — Frankendancer / Firedancer hybrid CalVer release (`9eGrDohdNTAo61DRHyfMuqKWXqYnA3i254Wiszxe8FoY` & `CQdLgwkmmHF8DE6t4sguXMTXWDxq3oLh3xfekDTmow12`)
  3. `26.10.3` — Earlier Frankendancer / Firedancer hybrid release (`FBbqKvwLfKGZrKrfSbPJz4ymQ7zMarhRyZtu1RBkSe89`)
  4. `4.4.0-rc.0` — Agave 4.4 Release Candidate canary (`mds4GEuiSgQRqveGyktWpETBFCb4AS2wDnhqwLHcT6Z`)
  5. `4.5.0-alpha.2` — Agave 4.5 Alpha canary (`sce3TfT81rxYYcdbP1kBFMcTK3ZBc8hvHVeXD6WLSzE`)
  6. `0.1.1` — Custom modular / Firedancer client (`AHZxzLeRGRfNVFrCmP58iJgEwbcXyZeAkZ32CmbfEmYR`)

### 3.2 Path of a Transaction from Backend to Executing Node
1. **Signing & Wire Serialization (`probe_builder.py`)**: Transactions are constructed with explicit `ComputeBudget` instructions (`SetComputeUnitLimit` tag `0x02`, `SetComputeUnitPrice` tag `0x03`), a 1-lamport `SystemProgram::Transfer` write-locking the target probe account, and a sequence-tagged `Memo` instruction, then signed with Ed25519.
2. **Ingress & Forwarding**: Transactions traverse RPC HTTP/JSON-RPC -> Stake-Weighted QoS (SWQoS) / unstaked QUIC forwarder -> Leader's `tpu_quic` port (resolved per validator via `getClusterNodes()[leader]["tpuQuic"]`).
3. **Validator Pipeline**: Packets enter `FetchStage` -> `SigVerifyStage` (Ed25519 batch verification + packet deduplication) -> `BankingStage` scheduler (`CentralScheduler` / `PrioGraph` in Agave; `fd_pack` tile in Frankendancer/Firedancer) -> `ConsumeWorker` execution -> continuous PoH `Entry` hashing.

### 3.3 Interaction of Our Own Transactions With Each Other
- Handled explicitly by separating `Mode A (REVERSE_FEE_CONTENDED)`—where our transactions deliberately collide on a single SHA-256-derived writable account so the validator *must* order them relative to one another—from `Mode B (DISJOINT_PARALLEL_LADDER)`—where each transaction touches a distinct SHA-256-derived writable account.

### 3.4 Competition Inside the Block
- Probe writable accounts are derived via `SHA256("tx-order-lab:...")` so external DEX/MEV transactions never write-lock our probe accounts.
- Simultaneously, our block analyzer measures **real contended write-lock queues (`LocalLock W<=16` and `Adjacent Shared-Lock delta=1`)** across all 4,601 transactions in the 8 target blocks to quantify how each validator orders competing transactions under live Mainnet load.

### 3.5 Send Order vs. Priority Fee
- In `REVERSE_FEE_CONTENDED`, probe `seq=1` is dispatched first with the **lowest** priority fee (`10,000` $\mu$lamports/CU) and `seq=6` is dispatched last with the **highest** priority fee (`60,000` $\mu$lamports/CU). Any positive concordance with priority fee proves active scheduler re-ordering against arrival order.

### 3.6 Noise vs. Rule
- We report three distinct statistical measures per validator (`src/tx_order_lab/analyzer.py`):
  1. **Global Block Spearman $\rho$ and Kendall $\tau_b$** across all $N$ transactions in the block.
  2. **Local Contended Write-Lock Concordance (`LocalLock W<=16`)**: Pairwise concordance rate, binomial $Z$-score, and two-sided $p$-value across transaction pairs sharing a writable account within a 16-transaction micro-window (~1–2 PoH ticks).
  3. **Adjacent Shared-Lock Concordance (`AdjLock delta=1`)**: Pairwise concordance across back-to-back transactions (`tx_index` and `tx_index + 1`) sharing a writable account.

### 3.7 Alpenglow Upgrade (October 21, 2026)
- **100% Post-Alpenglow Dataset**: Every block and measurement in this repository was captured on **October 26, 2026 UTC** (`Epoch 1068`, slots `461,696,595` to `461,701,395`), five days after the October 21 Alpenglow activation.
- Our parser natively handles post-Alpenglow `Version 1` transactions (`maxSupportedTransactionVersion: 1`), `message.transactionConfig`, and `meta.costUnits`.

---

## 4. What This Design Deliberately Does NOT Separate

1. **WAN / QUIC Arrival Jitter vs. Pre-Scheduler `SigVerifyStage` Queuing**: From external block observations and client-side send timestamps alone, if Transaction A lands before Transaction B across two different PoH ticks, we cannot distinguish whether Transaction B suffered 8ms of WAN/QUIC retransmission jitter or was delayed inside a `SigVerifyStage` packet batch before reaching `BankingStage`.
2. **SWQoS Staked Forwarding Priority vs. Scheduler Priority**: Validators allocate 80%+ of `tpu_quic` stream bandwidth to Stake-Weighted QoS (SWQoS) peers. Our design measures ordering *after* transactions enter the scheduler window, not packet drop probability at the QUIC ingress gate.
3. **Out-of-Protocol Jito Bundles**: Per the bounty specification, Jito bundles and tip-distribution auction mechanics are out of scope; our analysis evaluates the validator's native transaction scheduler (`reward / cost_units`).

---

## 5. Security & Spend-Cap Architecture (`src/tx_order_lab/spend_guard.py`)

- **Default `--dry-run` Mode**: `python3 -m tx_order_lab.cli` defaults to `--dry-run`. Live network broadcast requires passing `--live` explicitly.
- **Atomic `0.05 SOL` (`50,000,000 lamports`) Spend Cap**: `SpendCapGuard` enforces a hard ceiling of `50,000,000 lamports`. Every probe transaction reserves `base_fee_lamports + priority_fee_lamports` atomically *before* transmission; any transaction that would push cumulative spend above the cap raises `SpendCapExceededError` immediately.
- **Strict Key Isolation**: `load_signer_keypair()` resolves paths against the repository root and raises `KeySecurityError` if any keypair file resides inside the repository directory tree. Live keys may only be supplied via `SOLANA_PRIVATE_KEY` or an external read-only Docker volume (`SOLANA_KEYPAIR_PATH=/secrets/solana-keypair.json`).

---

## 6. Repository Layout & Raw Data Verification

```text
.
├── Dockerfile                         # Single-command reproducible container build
├── docker-compose.yml                 # One-command runner (docker compose up --build)
├── pyproject.toml                     # Package configuration
├── requirements.txt                   # Minimal dependencies (cryptography, pytest)
├── README.md                          # Experimental design, architecture & verification guide
├── REPORT.md                          # Full empirical report, measurement dates & "What Went Wrong"
├── src/tx_order_lab/
│   ├── spend_guard.py                 # 0.05 SOL atomic SpendCapGuard & repo-external key loader
│   ├── probe_builder.py               # Deterministic probe burst builder (Modes A, B, C)
│   ├── leader_window.py               # Post-Alpenglow RPC client & 4-slot leader window detector
│   ├── analyzer.py                    # Spearman rho, Kendall tau & contended-lock statistical engine
│   └── cli.py                         # CLI entrypoint (--dry-run default, --live gated)
├── tests/
│   ├── test_spend_guard.py            # Positive & negative tests for 0.05 SOL cap & key isolation
│   ├── test_probe_builder.py          # Probe transaction signing & writable-lock topology tests
│   └── test_analyzer.py               # Rank statistics & Mainnet dataset scope verification
└── data/
    ├── raw/
    │   ├── manifest.json              # Index of all 8 Mainnet slots & block timestamps
    │   ├── validators_metadata.json   # Gossip versions, stakes & TPU QUIC sockets for 8 validators
    │   ├── probe_cohorts.json         # Extracted multi-tx cohorts with verifiable signatures
    │   ├── slot_461701391_v4_3_2.json
    │   ├── slot_461701258_v4_3_2.json
    │   ├── slot_461701395_v26_10_4.json
    │   ├── slot_461701211_v26_10_4.json
    │   ├── slot_461701007_v26_10_3.json
    │   ├── slot_461699583_v4_4_0_rc_0.json
    │   ├── slot_461697411_v4_5_0_alpha_2.json
    │   └── slot_461696595_v0_1_1.json
    └── processed/
        ├── analysis_summary.json      # Complete statistical output across all 8 validators
        └── dry_run_execution_log.json # Signed probe bursts & spend-guard ledger
```

### Quick `getBlock` Verification Command for Judges

Judges can verify any slot or transaction signature in `data/raw/` directly against Solana Mainnet RPC (note that `"maxSupportedTransactionVersion": 1` is mandatory post-Alpenglow):

```bash
curl -s https://api.mainnet-beta.solana.com -X POST -H "Content-Type: application/json" -d '{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "getBlock",
  "params": [461701395, {"encoding": "json", "transactionDetails": "signatures", "maxSupportedTransactionVersion": 1}]
}' | jq '{blockhash: .result.blockhash, blockTime: .result.blockTime, txCount: (.result.signatures | length), first5Sigs: .result.signatures[:5]}'
```
