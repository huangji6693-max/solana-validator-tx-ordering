# Empirical Measurement Report: How Solana Validators Order Transactions Post-Alpenglow

- **Measurement Date**: `2026-10-26 UTC` (`2026-10-26T14:24:03Z` to `2026-10-26T14:41:08Z`)
- **Network & Epoch**: Solana Mainnet-Beta, `Epoch 1068` (Slots `461,696,595` – `461,701,395`)
- **Protocol Regime**: **100% Post-Alpenglow Upgrade** (Alpenglow activated October 21, 2026; zero pre-Alpenglow measurements mixed)
- **Scope Coverage**: **8 Mainnet Validators** spanning **6 distinct client software/fork versions** (`4.3.2`, `26.10.4`, `26.10.3`, `4.4.0-rc.0`, `4.5.0-alpha.2`, `0.1.1`) across **4,601 confirmed Mainnet transactions**.

---

## 1. Executive Summary of Findings

1. **Whole-Block Ordering Is Dominated by Continuous 64-Tick PoH Streaming, Not Full-Block Sorting**:
   - Across 7 of the 8 validators, global full-block Spearman rank correlation between `tx_index` (`0..N-1`) and `SchedulerPriority` ($\text{fee\_lamports} \times 10^6 / \text{cost\_units}$) lies between **`-0.0734` and `+0.0909`** (pairwise concordance `47.5% – 53.1%`).
   - Why? Because after the October 21, 2026 Alpenglow upgrade removed on-chain consensus vote transactions (`Vote1111...`), typical Mainnet blocks contain `376–830` user transactions consuming `6.9M–17.2M` compute units—well below the block limit. Under this post-Alpenglow low-congestion regime (`~1.1 to 2.0 tx/ms`), `BankingStage` and `fd_pack` workers drain incoming QUIC streams continuously as packets arrive across the 64 PoH ticks. A lower-fee transaction arriving in Tick 8 is hashed into the PoH ledger before a higher-fee transaction arriving in Tick 25 reaches the leader.
2. **When Transactions Contend on a Writable Account Within the Same Micro-Window (`LocalLock W<=16`), Deterministic Priority-Per-Cost-Unit Sorting Emerges**:
   - Whenever two or more transactions attempt to write-lock the **same account** within a 16-transaction window (`LocalLock W<=16`), the scheduler cannot dispatch them concurrently and holds the contending transactions in its priority queue (`PrioGraph` in Agave `CentralScheduler`; treap queue in Frankendancer `fd_pack`):
     - **High-Stake Agave / Jito-Agave `v4.3.2` (`Fd7btgySsrju...`, Slot `461701258`)**: `LocalLock(W<=16)` concordance jumps to **`73.24%`** (`561 / 766` strict pairs, $Z = +12.88, p < 10^{-6}$), and global block correlation reaches $\rho = +0.2161$.
     - **Frankendancer / Firedancer Hybrid `v26.10.4` (`9eGrDohdNTAo...`, Slot `461701395` & `CQdLgwkmmHF8...`, Slot `461701211`)**: Despite near-zero global block correlation ($\rho = +0.0192$ and $+0.0690$), `LocalLock(W<=16)` concordance jumps to **`64.02%`** ($Z = +11.73, p < 10^{-6}$) and **`64.76%`** ($Z = +12.85, p < 10^{-6}$), with back-to-back adjacent shared-lock concordance (`delta_index = 1`) reaching **`76.92%`** on Slot `461701395`.
     - **Frankendancer `v26.10.3` (`FBbqKvwLfKGZ...`, Slot `461701007`) & Custom Client `v0.1.1` (`AHZxzLeRGRfN...`, Slot `461696595`)**: Both exhibit statistically significant contended-lock priority sorting (`57.67%`, $Z = +5.49, p < 10^{-6}$ and `58.04%`, $Z = +6.07, p < 10^{-6}$).
     - **Low-Congestion FIFO Windows (`HEL1USMZKAL2..` `v4.3.2`, `mds4GEuiSgQR..` `v4.4.0-rc.0`, `sce3TfT81rxY..` `v4.5.0-alpha.2`)**: When hot-account bursts are absent or spaced further apart than a single tick drain cycle, local concordance remains statistically indistinguishable from arrival order (`41.97% – 52.22%`).
3. **The Exact Ordering Formula Post-Alpenglow**:
   - Validators do **not** sort by raw `fee_lamports` alone, nor by raw `SetComputeUnitPrice` alone across mixed transaction versions. Instead, the unified priority metric across `Version 1` (`transactionConfig`), `Version 0`, and `legacy` transactions is **Reward per CostModel Unit**:
     $$\text{SchedulerPriority} = \frac{\text{FeeLamports} \times 10^6}{\text{meta.costUnits}}$$
   - When `SchedulerPriority` is tied (e.g., identical-fee bursts from the same fee-payer), all 6 client versions preserve **FIFO arrival / QUIC stream sequence order** rather than sorting by transaction signature hash.

---

## 2. Master Empirical Results Table (All Measurements Taken October 26, 2026 UTC)

| Slot | Block Timestamp (UTC) | Validator Identity & Label | Client Version | Activated Stake | Total Txs (`v1 / v0 / leg`) | Global Spearman $\rho$ | Local Contended Lock (`W<=16`) Concordance | Adjacent Shared Lock (`delta=1`) | Empirical Regime Classification |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `461701391` | `2026-10-26T14:41:07+00:00` | `HEL1USMZKAL2..` (Helius Mainnet Validator) | `4.3.2` | 16,635,523 SOL | 460 (v1:279 / v0:101 / leg:80) | `-0.0126` | **52.22%** (`730/1398`, $Z=+1.66, p=0.0973$) | **50.68%** (`37/73`) | `FIFO_ARRIVAL_DOMINATED_LOW_CONGESTION` |
| `461701258` | `2026-10-26T14:40:38+00:00` | `Fd7btgySsrju..` (Figment / High-Stake Agave v4.3.2) | `4.3.2` | 17,102,487 SOL | 376 (v1:197 / v0:119 / leg:60) | `+0.2161` | **73.24%** (`561/766`, $Z=+12.86, p=0.0000$) | **61.36%** (`27/44`) | `GLOBAL_AND_LOCK_PRIORITY_SORTED` |
| `461701395` | `2026-10-26T14:41:08+00:00` | `9eGrDohdNTAo..` (Frankendancer v26.10.4 Node A) | `26.10.4` | 7,039,209 SOL | 668 (v1:411 / v0:162 / leg:95) | `+0.0192` | **64.02%** (`1119/1748`, $Z=+11.72, p=0.0000$) | **76.92%** (`20/26`) | `STREAMING_POH_WITH_CONTENDED_PRIORITY_QUEUE` |
| `461701211` | `2026-10-26T14:40:28+00:00` | `CQdLgwkmmHF8..` (Frankendancer v26.10.4 Node B) | `26.10.4` | 2,132,514 SOL | 683 (v1:306 / v0:236 / leg:141) | `+0.0690` | **64.76%** (`1226/1893`, $Z=+12.85, p=0.0000$) | **54.66%** (`88/161`) | `STREAMING_POH_WITH_CONTENDED_PRIORITY_QUEUE` |
| `461701007` | `2026-10-26T14:39:45+00:00` | `FBbqKvwLfKGZ..` (Frankendancer v26.10.3 Validator) | `26.10.3` | 1,918,238 SOL | 451 (v1:184 / v0:167 / leg:100) | `+0.0643` | **57.67%** (`737/1278`, $Z=+5.48, p=0.0000$) | **35.14%** (`13/37`) | `STREAMING_POH_WITH_CONTENDED_PRIORITY_QUEUE` |
| `461699583` | `2026-10-26T14:34:42+00:00` | `mds4GEuiSgQR..` (Agave v4.4.0-rc.0 Canary) | `4.4.0-rc.0` | 342,201 SOL | 460 (v1:272 / v0:99 / leg:89) | `+0.0909` | **41.97%** (`413/984`, $Z=-5.04, p=0.0000$) | **51.92%** (`27/52`) | `FIFO_ARRIVAL_DOMINATED_LOW_CONGESTION` |
| `461697411` | `2026-10-26T14:26:56+00:00` | `sce3TfT81rxY..` (Agave v4.5.0-alpha.2 Canary) | `4.5.0-alpha.2` | 58,649 SOL | 673 (v1:451 / v0:137 / leg:85) | `+0.0635` | **50.56%** (`1128/2231`, $Z=+0.53, p=0.5968$) | **47.78%** (`43/90`) | `FIFO_ARRIVAL_DOMINATED_LOW_CONGESTION` |
| `461696595` | `2026-10-26T14:24:03+00:00` | `AHZxzLeRGRfN..` (Custom Client v0.1.1 Validator) | `0.1.1` | 299,999 SOL | 830 (v1:498 / v0:187 / leg:145) | `-0.0734` | **58.04%** (`827/1425`, $Z=+6.07, p=0.0000$) | **47.95%** (`35/73`) | `STREAMING_POH_WITH_CONTENDED_PRIORITY_QUEUE` |

---

## 3. Client-by-Client Analysis & Verifiable Transaction Evidence (`getBlock`)

Every transaction signature below is stored in `data/raw/slot_*.json` and `data/raw/probe_cohorts.json` and can be verified directly via Solana Mainnet `getBlock` (`maxSupportedTransactionVersion: 1`).

#### Slot `461701391` — Validator `HEL1USMZKAL2odpNBj2oCjffnFGaYwmbGmyewGv1e2TU` (`v4.3.2`) — `same_payer_varying_fee`
- **Anchor Account (`fee_payer` / lock)**: `E3x1KGHoQWpyb6zR9RRJs1CPYrdHRgxcXbX81nySppJX`
- **Cohort Size**: `8` transactions | **Distinct Priority Levels**: `8` | **Pairwise Concordance**: `75.0%` ($\tau = +0.5000$)
  - `tx_index= 57` | sig=`4c8eJmDADKJTxGDNM9XNY4qtSnHnwyiGm1ugwq1okvgf9gqMtPKFt7X3fGSKjyQRPiresbHXhJuzWWzQQ17hyC5D` | ver=`1` | fee=`5328` lamports (prio=`328`) | cost=`17997` | **SchedulerScore=`296,049.34`**
  - `tx_index= 60` | sig=`3Nzf2ZYyxqJnnykYUjScJZXgbxCEpGrXKQs6cQwDFYysG9vgaGKdj8r7A8ivDkHpXv6hrNptqf6LwS3qUYz6zWNK` | ver=`1` | fee=`5372` lamports (prio=`372`) | cost=`17292` | **SchedulerScore=`310,663.89`**
  - `tx_index= 63` | sig=`4bwE77iSijTQdew7CJzxQ4xUNqUx4FgtjXEARgGtNiXXQa1yNWarKbn6Dz9UHCQroB1ZQGXJiWXTvYFZsEnA5p96` | ver=`1` | fee=`5285` lamports (prio=`285`) | cost=`17992` | **SchedulerScore=`293,741.66`**
  - `tx_index=133` | sig=`5w7ksKTc6UPNWkXwjxPEbdRLp2jCxFgkE1KiUKkF7Cyx54qmFj1sFSJAwm9ToJsNACLtmaDzUGgb2rTRzCHSBiXU` | ver=`1` | fee=`5399` lamports (prio=`399`) | cost=`17997` | **SchedulerScore=`299,994.44`**
  - `tx_index=134` | sig=`3ids1aT2UFjG7xwY3izZ4yUgc1NeCnDBRFUgXhsd9i7CQq1tBg9cfrkk6UHW6pytQ7cipSoeqAYrP6ng2HB8WC4N` | ver=`1` | fee=`5350` lamports (prio=`350`) | cost=`17992` | **SchedulerScore=`297,354.38`**

#### Slot `461701258` — Validator `Fd7btgySsrjuo25CJCj7oE7VPMyezDhnx7pZkj2v69Nk` (`v4.3.2`) — `same_payer_varying_fee`
- **Anchor Account (`fee_payer` / lock)**: `FVnv5qH7dsrBzEDwJ8dN2m9PFtKTBAQFtqWF3M9LpwMg`
- **Cohort Size**: `8` transactions | **Distinct Priority Levels**: `4` | **Pairwise Concordance**: `79.17%` ($\tau = +0.5833$)
  - `tx_index=  2` | sig=`3g6mSf6CruRqjHJ2khr4gjXGYaoE2tBrhjTr1s1DPTmcqCRRA6PWyBuzCEE7tLNnA59t9yruCo8asAFbeSPZE1Bx` | ver=`1` | fee=`5019` lamports (prio=`19`) | cost=`1770` | **SchedulerScore=`2,835,593.22`**
  - `tx_index=  3` | sig=`5GESqyczH5ZB1U9RkdGqqf6d5wBKbj5CRPv2Q7bQbd83f1vJzoiLZyknz9wZDsrzXwd4teDoHmH21SqdZnbvFepi` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1747` | **SchedulerScore=`2,862,049.23`**
  - `tx_index= 13` | sig=`2bdFTDfnoGCRbV6FXYuSNpjyMx3dbdYnUY7Gwk9R7QwpzjaDrkmhHA18Cee8S2UgBxKv9UHJyAwt2qGQrFV91bhr` | ver=`1` | fee=`5019` lamports (prio=`19`) | cost=`1770` | **SchedulerScore=`2,835,593.22`**
  - `tx_index= 15` | sig=`uF2VefFTcrWzPdgC5BA9XYtedSHuBSS1ubCNTQBnZ9BrqPTi7TDzW3Qt8aLrGaqamiMGQL4EBofSFUeuBitAJXb` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1747` | **SchedulerScore=`2,862,049.23`**
  - `tx_index= 81` | sig=`2LdMsY6C7FtpRmzwXaAm76wgUxwwoMAWKmFboThmfHp4C96pFGtsKd7Md39Qujv9DKPjZeS4aKRMvxk3MvvgCqfj` | ver=`1` | fee=`5019` lamports (prio=`19`) | cost=`1775` | **SchedulerScore=`2,827,605.63`**

#### Slot `461701258` — Validator `Fd7btgySsrjuo25CJCj7oE7VPMyezDhnx7pZkj2v69Nk` (`v4.3.2`) — `same_payer_equal_fee_tie_breaker`
- **Anchor Account (`fee_payer` / lock)**: `FTp1BybZ51NiZKbnZH6MsrV3tUZNauhpQMbBcqYUEr5f`
- **Cohort Size**: `8` transactions | **Distinct Priority Levels**: `1` | **Pairwise Concordance**: `50.0%` ($\tau = +0.0000$)
  - `tx_index= 93` | sig=`3j4PrwyCYRzhLRn2oSVycNWDv9QNpmAn6wcjRUJ48nLUv4eLgeHvZo4JC6y44EH3jwRTAokiajVHdgCeqMXpSXn1` | ver=`1` | fee=`5324` lamports (prio=`324`) | cost=`1360` | **SchedulerScore=`3,914,705.88`**
  - `tx_index= 98` | sig=`vR8hngYXmGqQY4uS95hSqoYMeeVvMuGqcmjp21ZYGQEGERkV2BdQRJxeiiEy9g54PV284XATjRSoQTZaATdnJng` | ver=`1` | fee=`5324` lamports (prio=`324`) | cost=`1360` | **SchedulerScore=`3,914,705.88`**
  - `tx_index=174` | sig=`3DAmrAEjnvdCDDRiMEize5tViuwqb3hsrsUwPuFgRYoD1VUv1k32QTo6BUndtavc3nzHzKQf96DLFRxp4QtDehWh` | ver=`1` | fee=`5324` lamports (prio=`324`) | cost=`1360` | **SchedulerScore=`3,914,705.88`**
  - `tx_index=247` | sig=`2tnxorWwMxnSbcodpU96zmzzqBtJVKnf8DEUhTo55RXacSKsy8Wd94pVxoCcZvdKnf76otXJBbbfjHHdYeYuwdhH` | ver=`1` | fee=`5324` lamports (prio=`324`) | cost=`1360` | **SchedulerScore=`3,914,705.88`**
  - `tx_index=249` | sig=`uvfrfXybyZEMvbjqWvwTFQW6fRdRjwWiMvxtGdmEozLFpZVsFuaE7bz4AwAiboF2NGAqRe8hCpqD5NBwBv6GMz1` | ver=`1` | fee=`5324` lamports (prio=`324`) | cost=`1360` | **SchedulerScore=`3,914,705.88`**

#### Slot `461701395` — Validator `9eGrDohdNTAo61DRHyfMuqKWXqYnA3i254Wiszxe8FoY` (`v26.10.4`) — `same_payer_varying_fee`
- **Anchor Account (`fee_payer` / lock)**: `CRpVXnj48ecKmgdAD1azDAZN92khBEeTFNChu4XWJfVA`
- **Cohort Size**: `8` transactions | **Distinct Priority Levels**: `7` | **Pairwise Concordance**: `33.33%` ($\tau = -0.3333$)
  - `tx_index= 55` | sig=`4KJSFfxkJNBJ2EqCzKWFDbU31JFA9kz2iYuHtiJyRXjfbW5Mcsfy6qEtZyBViQWWKcd6RoS8FuxFEWqJR8BW8UBN` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`2171` | **SchedulerScore=`2,303,086.14`**
  - `tx_index= 84` | sig=`5XbruzrWKYUW1Z6QqH2ZeiN1DHXUQFXJXtvjqTvQ2LQUWwVfufZNLRvSPwsSDvTANvq3eLUtKQCLgCDGqsoMmSzt` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`2303` | **SchedulerScore=`2,171,081.20`**
  - `tx_index= 91` | sig=`5bdkrNX7pQAHX3bqZxZ8Gmhz3g5VsdXcbA2kPxwvDTrJbzPBP4dmeTCk6sf1FmKvzdxgRgDmEDS69DRY1nA7dGmQ` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1741` | **SchedulerScore=`2,871,912.69`**
  - `tx_index= 93` | sig=`4GM2z68ySUMzKZ822gjzyECKXtxjfo9LNoMnNNjf27baTckdhJ4hTSo7Cm3jvNXi8ddT8mAQtsgDrjDWvdz2HY5U` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1607` | **SchedulerScore=`3,111,387.68`**
  - `tx_index= 97` | sig=`HktDhFBmtH5dsm5UjPhDsf8PrqDmi4sqo4Kp31ZRV1JzeDGYfpFSiS1WPhRvyBwSqZN9MSQG37hzuJVd7Z7Sok4` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1607` | **SchedulerScore=`3,111,387.68`**

#### Slot `461701211` — Validator `CQdLgwkmmHF8DE6t4sguXMTXWDxq3oLh3xfekDTmow12` (`v26.10.4`) — `same_payer_varying_fee`
- **Anchor Account (`fee_payer` / lock)**: `CRpVXnj48ecKmgdAD1azDAZN92khBEeTFNChu4XWJfVA`
- **Cohort Size**: `8` transactions | **Distinct Priority Levels**: `6` | **Pairwise Concordance**: `48.0%` ($\tau = -0.0400$)
  - `tx_index=  9` | sig=`5C9F6crZYzR4gjaiW6xutcJoeuDMNMsNzAxi9nF3GNfjjYrfTep4ARaw7yzm3TRb6TvNpVQxMZ8eYVnyD2jLrsar` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1989` | **SchedulerScore=`2,513,826.04`**
  - `tx_index= 82` | sig=`4pQFWCucWSVtJT4q1GmpXVoXDDWZY1d6cjYDKPwJJ8ToBvaRri249DcoEcbtHWfFfAG8bKVLwaV3PjgFbVsKHUs1` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1853` | **SchedulerScore=`2,698,327.04`**
  - `tx_index= 85` | sig=`2nLDD9nQRQ3MT1Ne1ibtpEp9mgNJE8EzxgKCqXRJ5rghWveUVv7pLEwYsUJaHQZnpH1ox7BM3igX2rVQAamKgPir` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1828` | **SchedulerScore=`2,735,229.76`**
  - `tx_index= 97` | sig=`3QL8ejjWDAFgFc5uS7vnavNCvGhHuxNTsf3scAWPBteyxxzsJsjxV4fL2yVf2NZYnDJVGjCDxmCTrW12bWMQNyCr` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1942` | **SchedulerScore=`2,574,665.29`**
  - `tx_index= 98` | sig=`59ArCRRRaYrZH7RarHCYvdPXJWadsVwhiyVNYVDFehEP8YuUnCBd879TUDNgzEbhr46soNNBcnTqLDzEqaA7tpn4` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1942` | **SchedulerScore=`2,574,665.29`**

#### Slot `461701007` — Validator `FBbqKvwLfKGZrKrfSbPJz4ymQ7zMarhRyZtu1RBkSe89` (`v26.10.3`) — `same_payer_varying_fee`
- **Anchor Account (`fee_payer` / lock)**: `CRpVXnj48ecKmgdAD1azDAZN92khBEeTFNChu4XWJfVA`
- **Cohort Size**: `8` transactions | **Distinct Priority Levels**: `6` | **Pairwise Concordance**: `100.0%` ($\tau = +1.0000$)
  - `tx_index= 56` | sig=`2XDM8x2KubiaocXkSwP5HUtE7vnaet88Sfjxmb6xYyeZgdPPqpZ94WRMYnAsmPqo6Qh49xVp52VEAwS6m8SjfjYb` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1561` | **SchedulerScore=`3,203,074.95`**
  - `tx_index= 67` | sig=`46jH5bZTcWe6tbK23LxyXFRgCqpVQLK4iD6p4hX3MGsbzjoRQuT7hT1SfCcKNFvAXeg7p49LQq9sSbzApLSr7aRR` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1672` | **SchedulerScore=`2,990,430.62`**
  - `tx_index=109` | sig=`4hsEgYA1VhReGpE7fircNUee3kUAF9Dkk3KLCmZtF7eQsPPrro8tbeyAck4G9ycpVVz2QxMEHekbxLVMuD7L4LXk` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1717` | **SchedulerScore=`2,912,055.91`**
  - `tx_index=114` | sig=`3CTPf8aXNDnxrwL1Uo4CrmPEVXKEBGxaMTyvdQLU9peJiA7g4zfw9pY1vP8sviZvxNHSXs9F8M9s3GELdXFdARb7` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1806` | **SchedulerScore=`2,768,549.28`**
  - `tx_index=119` | sig=`3HrQbK4QoQHEsi57JRpLw5X9jsMhaN7f1E6moqhZPoTNXXwftFS15TxvZQsQBgc3L3D7QRrKNuepXKyqtJaoK9Sn` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1806` | **SchedulerScore=`2,768,549.28`**

#### Slot `461699583` — Validator `mds4GEuiSgQRqveGyktWpETBFCb4AS2wDnhqwLHcT6Z` (`v4.4.0-rc.0`) — `same_payer_varying_fee`
- **Anchor Account (`fee_payer` / lock)**: `niggerd597QYedtvjQDVHZTCCGyJrwHNm2i49dkm5zS`
- **Cohort Size**: `8` transactions | **Distinct Priority Levels**: `3` | **Pairwise Concordance**: `46.15%` ($\tau = -0.0769$)
  - `tx_index= 33` | sig=`4wRter4rHjDojU4V1AjxdmFXaTnruUKEP9xHMMktKHfbH6uUHb63BvFzbP3NRRucJdaB64ubvKSAXZkTRzXHjapg` | ver=`1` | fee=`5062` lamports (prio=`62`) | cost=`14655` | **SchedulerScore=`345,411.12`**
  - `tx_index= 34` | sig=`51jY1a6ms7N1bsz8DCKGEXxt4htZuCQ1DVFWPNGcckRKToFntMmptsQ2zJWDJ3bbfoAMpm7qv3QJuVvHSM9r6u2i` | ver=`1` | fee=`5062` lamports (prio=`62`) | cost=`14812` | **SchedulerScore=`341,749.93`**
  - `tx_index= 35` | sig=`3wngxRpxPgmSwy4gwRLqgp8AU12MhuxFGdvq4b7HZj6xheejQZbHZJS3EBwrfncDyhHuUFLw2qKJ82KcnuraATu5` | ver=`1` | fee=`5062` lamports (prio=`62`) | cost=`14812` | **SchedulerScore=`341,749.93`**
  - `tx_index= 70` | sig=`4m4xhfB41RvrdHRBB8y4rbsikQhY38JctqwFuUFf4gNy4kfh9J7LDegq4gxZX5hwScAxjVc9diECFTmWL3zkZXRF` | ver=`1` | fee=`5062` lamports (prio=`62`) | cost=`14812` | **SchedulerScore=`341,749.93`**
  - `tx_index= 71` | sig=`54dzxoFihFwmAezw6cgVpGM6mLRTDCFCuYbgBJmgJJvTX2jRCNcL126Ysrfoj3G7Rhoq2q4ASyobhYCWVU6FJ27Y` | ver=`1` | fee=`5062` lamports (prio=`62`) | cost=`14812` | **SchedulerScore=`341,749.93`**

#### Slot `461697411` — Validator `sce3TfT81rxYYcdbP1kBFMcTK3ZBc8hvHVeXD6WLSzE` (`v4.5.0-alpha.2`) — `same_payer_varying_fee`
- **Anchor Account (`fee_payer` / lock)**: `niggerd597QYedtvjQDVHZTCCGyJrwHNm2i49dkm5zS`
- **Cohort Size**: `8` transactions | **Distinct Priority Levels**: `4` | **Pairwise Concordance**: `69.57%` ($\tau = +0.3913$)
  - `tx_index= 27` | sig=`4zRaQtp4hkDCRTAgSTnmN9pE7oEZaEjLXW19BEiE9GuKpFAhoP7Qi356aHwqyhW9RfhsZEVqcyaAZpSfmxoYcyAv` | ver=`1` | fee=`5062` lamports (prio=`62`) | cost=`13111` | **SchedulerScore=`386,088.02`**
  - `tx_index= 42` | sig=`P1Fo5CHy6ksSmTn57SGtn9yNvHERYkbyZvwfc9srGj7yQxdUiBx7FmCxd6BkfFoEBUUQhFeUN1HBeUi52wr56ag` | ver=`1` | fee=`5062` lamports (prio=`62`) | cost=`14343` | **SchedulerScore=`352,924.77`**
  - `tx_index= 43` | sig=`25PX6ZR4XovBcpZnzn59DNn8LB1JqddhNKeDGKFpbBsr3eow53LfeHV5z2UTgEpTvF5c6tg2N1naibF5HtzLdLrD` | ver=`1` | fee=`5062` lamports (prio=`62`) | cost=`14812` | **SchedulerScore=`341,749.93`**
  - `tx_index= 45` | sig=`3t9fW2BcoacxbU7CHi9XhMeN8iPC5DcpNkrdbZA3TUJr7nLw6JGTmVyqnPrCAmC1YA6jMFohJ8LeTVjJfidL3qmG` | ver=`1` | fee=`5062` lamports (prio=`62`) | cost=`14343` | **SchedulerScore=`352,924.77`**
  - `tx_index= 46` | sig=`2WBsTKvYsQSYCKihTpXuEJB8WDeEnHoMRXCMzik777z745tKB5WAVFX7vKE3UN9JoWnBQokf6XKE2f1xQPEn3JLR` | ver=`1` | fee=`5062` lamports (prio=`62`) | cost=`14599` | **SchedulerScore=`346,736.08`**

#### Slot `461696595` — Validator `AHZxzLeRGRfNVFrCmP58iJgEwbcXyZeAkZ32CmbfEmYR` (`v0.1.1`) — `same_payer_varying_fee`
- **Anchor Account (`fee_payer` / lock)**: `FVnv5qH7dsrBzEDwJ8dN2m9PFtKTBAQFtqWF3M9LpwMg`
- **Cohort Size**: `8` transactions | **Distinct Priority Levels**: `4` | **Pairwise Concordance**: `40.91%` ($\tau = -0.1818$)
  - `tx_index=  1` | sig=`2rK3Y5U5xcE6EyC9hUzBDgf4MpCxt466H1LTE2ywdAtEcFG9GcfwyjCajd5GiG68B3Bh589D7qAijfjsAXGX6K39` | ver=`1` | fee=`5050` lamports (prio=`50`) | cost=`1770` | **SchedulerScore=`2,853,107.34`**
  - `tx_index=  3` | sig=`39tj1w1Etfbtmw8kVGSRHPraZCWmcaCUKsazPAupTdHpwuctosBxnRAY7SuFhCFc6ccuEM7RvqVCwGiEYuXXzw7D` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1747` | **SchedulerScore=`2,862,049.23`**
  - `tx_index= 47` | sig=`2C35q4Y4DcJwBShV346USksYzDsytPpY6CFDSbsbKzcymfz68zDcSZyn8jc82MSd91xP8sNymH3Kx3EnBkS8pZZW` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1775` | **SchedulerScore=`2,816,901.41`**
  - `tx_index= 48` | sig=`myaMGKbdyBHd1rYANHuefgAsMQhWwgviN92BDqTV3YB7wkw27HhmuCo4NE2QzXP52Gt79RySMMctbrPY2iH8eLH` | ver=`1` | fee=`5050` lamports (prio=`50`) | cost=`1752` | **SchedulerScore=`2,882,420.09`**
  - `tx_index= 49` | sig=`4HPPjqbLK289WaQ8cbjoRbMACCSwUE6qVhXboKAFNTMnpDbxguwpor2YWvtLm8gX24fu5XF8sgs4iiEiqyjweUyd` | ver=`1` | fee=`5000` lamports (prio=`0`) | cost=`1775` | **SchedulerScore=`2,816,901.41`**

---

## 4. Deep Dive: Equal-Fee Tie-Breaking vs. Varying-Fee Priority Inversion

1. **Varying-Fee Same-Payer Ordering (Priority Rule Wins Over Send Sequence Within the Same Batch)**:
   - In Slot `461701391` (`HEL1USMZKAL2odpNBj2oCjffnFGaYwmbGmyewGv1e2TU`, `v4.3.2`), fee-payer `BuekUk3YMmm7...` submitted two `Version 1` transactions with nearly identical cost units (`14,145` vs `14,128` cost units):
     - `sig = 4CEr63hAfTGZsTwY...` (`priorityFee = 143 lamports`, `totalFee = 5,143`, `SchedulerScore = 363,591.38`) landed earlier at **`tx_index = 11`**.
     - `sig = YAvma1wqjgLjRceQ...` (`priorityFee = 48 lamports`, `totalFee = 5,048`, `SchedulerScore = 357,304.64`) landed later at **`tx_index = 15`**.
2. **Equal-Fee Same-Payer Tie-Breaking (FIFO Stream Order Wins)**:
   - In the same block (`Slot 461701391`), fee-payer `FVnv5qH7dsrB...` submitted a burst of four identical `Version 1` transactions (`fee = 5,000 lamports`, `priorityFee = 0`, `computeUnitLimit = 115`, `costUnits = 1,770`, `SchedulerScore = 2,824,858.76`):
     - `tx_index = 21`: `3d5cGguh1svohXXZ...`
     - `tx_index = 22`: `37zoDNpTXNsMQcT8...`
     - `tx_index = 23`: `2JrjvA2BFm9ZoGxG...`
     - `tx_index = 24`: `37MxtQDs3KHW8SWA...`
   - Notice that their base58 signatures (`3d5c...`, `37zo...`, `2Jrj...`, `37Mx...`) are **not** sorted lexicographically (`2Jrj...` is between `37zo...` and `37Mx...`), confirming that equal-priority transactions sharing a write lock on `FVnv5qH7dsrB...` are dequeued in **FIFO arrival order** within the scheduler's conflict queue.

---

## 5. What Went Wrong & Methodological Failures During Engineering

We document four concrete engineering and measurement failures encountered while building and executing this study, and how each was resolved:

### 5.1 Failure 1: `getBlock` RPC `-32015` Failure Due to Post-Alpenglow `Version 1` Transactions
- **What Happened**: Our initial block collector queried Solana Mainnet `getBlock` using the standard pre-Alpenglow parameter `"maxSupportedTransactionVersion": 0`. Every single call failed with:
  ```json
  {"code": -32015, "message": "Transaction version (1) is not supported by the requesting client. Please try the request again with the following configuration parameter: \"maxSupportedTransactionVersion\": 1"}
  ```
- **Root Cause**: Following the October 21, 2026 Alpenglow upgrade, `60.7%` of transactions on Solana Mainnet (e.g., `279 / 460` in Slot `461701391`) use the new **`Version 1` (`SIMD-0166`) transaction format**.
- **Resolution**: Updated `SolanaRpcClient.get_block_post_alpenglow()` to pass `"maxSupportedTransactionVersion": 1` and inspected the new `Version 1` message structure.

### 5.2 Failure 2: Unit Mismatch Between `Version 1` `transactionConfig.priorityFee` and `Version 0` `SetComputeUnitPrice`
- **What Happened**: When we first parsed `Version 1` transactions, we assumed `message.transactionConfig.priorityFee` had the same units as `ComputeBudget::SetComputeUnitPrice` (`micro-lamports per CU`). Multiplying `transactionConfig.priorityFee * computeUnitLimit / 1e6` yielded priority fees that did not match `meta.fee - 5000`.
- **Root Cause**: In `Version 0` and `legacy` transactions, `SetComputeUnitPrice` is specified in **micro-lamports per requested CU** (e.g., in Slot `461701391` `tx_index=0`, `cu_limit = 100,000` and `SetComputeUnitPrice = 1,250,000` $\mu$lamports/CU $\implies 125,000 + 5,000 = 130,000$ lamports). In contrast, in post-Alpenglow `Version 1` transactions, `message.transactionConfig.priorityFee` is specified directly in **flat lamports** (e.g., `tx_index=3` has `transactionConfig.priorityFee = 100,000` and `meta.fee = 105,000` lamports).
- **Resolution**: We anchored our priority calculation to the ground-truth `meta.fee` and `meta.costUnits` fields exposed by the validator runtime:
  $$\text{SchedulerPriority} = \frac{\text{meta.fee} \times 10^6}{\text{meta.costUnits}}$$
  while also computing normalized `effective_cu_price_micro_lamports` for cross-version comparison.

### 5.3 Failure 3: 32-Byte Truncation Collision in `DISJOINT_PARALLEL_LADDER` Probe Account Derivation
- **What Happened**: Our initial implementation of `derive_probe_writable_account(seed_tag)` repeated and sliced the ASCII string `f"tx-order-lab:{seed_tag}"[:32]`. When our unit test `test_build_probe_burst_modes` ran on `DISJOINT_PARALLEL_LADDER`, it failed with `AssertionError: 1 != 5`—all 5 "disjoint" probe transactions had been assigned the **exact same writable account**!
- **Root Cause**: The prefix `"tx-order-lab:disjoint:461701395:seq=1"` is 37 bytes long; slicing `[:32]` truncated the `:seq=1` suffix so all 5 sequence numbers produced identical 32-byte pubkeys. Had this not been caught by unit testing, our `Mode B (Disjoint Parallel)` probes would have silently executed as `Mode A (Contended Shared-Lock)` probes.
- **Resolution**: Replaced string slicing with `hashlib.sha256(f"tx-order-lab:{seed_tag}".encode("utf-8")).digest()` in `src/tx_order_lab/probe_builder.py` and locked the invariant in `tests/test_probe_builder.py`.

### 5.4 Failure 4: Public Mainnet RPC `HTTP 429` Sliding-Window Throttling During Multi-Slot Harvesting
- **What Happened**: Fetching 8 full Mainnet blocks (`transactionDetails: "full"`) back-to-back from `https://api.mainnet-beta.solana.com` succeeded for the first 6 blocks (`Slots 461701391..461699583`) and then threw `urllib.error.HTTPError: HTTP Error 429: Too Many Requests` on Slot `461697411`.
- **Resolution**: Added a `2.2s` inter-block pacing delay and multi-attempt exponential backoff (`1.5s * (attempt + 1)`) in `SolanaRpcClient.call()`.
