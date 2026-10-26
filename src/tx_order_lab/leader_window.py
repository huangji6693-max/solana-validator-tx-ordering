"""Solana Mainnet leader window detector and post-Alpenglow RPC client."""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional

DEFAULT_MAINNET_RPC = "https://api.mainnet-beta.solana.com"
CONSECUTIVE_LEADER_SLOTS = 4


@dataclass(frozen=True)
class LeaderWindow:
    validator_identity: str
    client_version: str
    tpu_quic: Optional[str]
    activated_stake_sol: float
    start_slot: int
    end_slot: int
    target_interior_slot: int  # slot_0 + 1 or slot_0 + 2 to avoid boundary handoff jitter


class SolanaRpcClient:
    """Rate-limit-resilient JSON-RPC client supporting post-Alpenglow Version 1 transactions."""

    def __init__(self, rpc_url: str = DEFAULT_MAINNET_RPC, timeout_sec: int = 30) -> None:
        self.rpc_url = rpc_url
        self.timeout_sec = timeout_sec

    def call(self, method: str, params: Optional[list[Any]] = None, max_retries: int = 5) -> Any:
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }).encode("utf-8")

        last_err: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(
                    self.rpc_url,
                    data=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "tx-order-lab/1.0"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    if "error" in body:
                        raise RuntimeError(f"RPC error on {method}: {body['error']}")
                    return body.get("result")
            except Exception as exc:
                last_err = exc
                time.sleep(1.5 * (attempt + 1))
        raise RuntimeError(f"RPC {method} failed after {max_retries} attempts: {last_err}")

    def get_epoch_info(self) -> dict[str, Any]:
        return self.call("getEpochInfo")

    def get_latest_blockhash(self) -> str:
        res = self.call("getLatestBlockhash", [{"commitment": "confirmed"}])
        return res["value"]["blockhash"]

    def get_slot_leaders(self, start_slot: int, limit: int = 400) -> list[str]:
        return self.call("getSlotLeaders", [int(start_slot), int(limit)])

    def get_cluster_nodes(self) -> dict[str, dict[str, Any]]:
        nodes = self.call("getClusterNodes")
        return {n["pubkey"]: n for n in nodes if n.get("pubkey")}

    def get_block_post_alpenglow(self, slot: int) -> dict[str, Any]:
        """
        Fetch confirmed Mainnet block with maxSupportedTransactionVersion: 1 (required after Oct 21 Alpenglow upgrade).
        """
        return self.call(
            "getBlock",
            [
                int(slot),
                {
                    "encoding": "json",
                    "transactionDetails": "full",
                    "maxSupportedTransactionVersion": 1,
                    "rewards": True,
                },
            ],
        )


def detect_upcoming_leader_windows(
    leaders: list[str],
    base_slot: int,
    cluster_nodes: dict[str, dict[str, Any]],
    stake_by_validator: Optional[dict[str, float]] = None,
) -> list[LeaderWindow]:
    """
    Group consecutive slot leaders into 4-slot rotation windows and select slot_0 + 1
    as the target interior slot to avoid leader handoff packet forwarding noise.
    """
    windows: list[LeaderWindow] = []
    stake_map = stake_by_validator or {}
    n = len(leaders)
    i = 0
    while i < n:
        leader = leaders[i]
        j = i
        while j + 1 < n and leaders[j + 1] == leader and (j + 1 - i) < CONSECUTIVE_LEADER_SLOTS:
            j += 1
        start_s = base_slot + i
        end_s = base_slot + j
        # Pick interior slot (start_s + 1) when window has >= 2 slots
        interior_s = start_s + 1 if (end_s > start_s) else start_s
        node_info = cluster_nodes.get(leader, {})
        windows.append(
            LeaderWindow(
                validator_identity=leader,
                client_version=node_info.get("version") or "unknown",
                tpu_quic=node_info.get("tpuQuic"),
                activated_stake_sol=round(stake_map.get(leader, 0.0), 2),
                start_slot=start_s,
                end_slot=end_s,
                target_interior_slot=interior_s,
            )
        )
        i = j + 1
    return windows
