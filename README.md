# Solana MultiHopper Programmable Treasury, Payroll & OTC Settlement Router

> **Built for the [MultiHopper Build & Route Challenge ($5,000 – $50,000 Pool + 0.25% Revenue Share)](https://superteam.fun/earn/listing/multihopper-build-and-route-challenge-up-to-dollar50000-revenue-share-1)**  
> **Solana Payout Wallet**: `AyXYaA9Nf4z5fpLKY6DmubWe6D2qveMd79w8pEDNHcDw`  
> **Superteam Agent Claim Code**: `F2CF6E122CB755F40CFCC895`

---

## 1. User Problem & Product Solution

Organizations, AI agent treasuries, and OTC desks operating on Solana face a critical operational dilemma:
1. **Public Account Graph Linkage**: Standard SPL transfers expose payroll schedules, supplier pricing, and treasury cold-wallet balances to anyone watching a single block explorer.
2. **Compliance Liability**: Privacy-focused mixing pools commingle funds and violate institutional compliance standards.
3. **Fragmented Multi-Send Reconciliation**: Launch distributions and contributor payroll require batching, safe retries, and cryptographic completion webhooks.

**`solana-multihopper-router`** solves this by combining **MultiHopper's non-commingled programmable multi-hop & Multi-Send routing** with **built-in TRM Labs smart-contract compliance screening** and **HMAC-signed completion webhooks**:
- **Discreet Non-Commingled Routing**: Routes SOL, USDC (`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`), and USDT across configurable relay hops without pooling or commingling customer funds.
- **Default TRM Labs Compliance Gate**: Every sender and recipient address is screened prior to route execution; sanctioned or high-risk addresses are rejected deterministically.
- **Exact Fee & Qualifying Volume Accounting**:
  - Full-rate fee: `0.50%` (`50 bps`), split `50/50` into **`0.25%` (`$2,500 per $1M`) direct partner revenue** and **`0.25%` competition prize pool funding**.
  - Enforces the exact campaign rules: principal counted once across hops and Multi-Send recipients (`Qualifying Volume = Collected MultiHopper Fee / 0.0025`), proportional credit for discounted transfers, and strict exclusion of devnet, circular, or refunded transfers.

---

## 2. Quickstart & Verification

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

### Verified Test Suite Output
```text
test_circular_self_transfer_rejected ... ok
test_devnet_volume_excluded_from_qualifying_volume ... ok
test_discounted_fee_scales_qualifying_volume_proportionally ... ok
test_multi_send_principal_counted_once_and_revenue_split ... ok
test_prize_pool_unlock_schedule_and_proportional_allocation ... ok
test_signed_completion_webhook_verification ... ok
test_trm_compliance_blocks_sanctioned_recipient ... ok
----------------------------------------------------------------------
Ran 7 tests in 0.004s — OK
```
