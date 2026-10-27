from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List


MIN_PRODUCT_QUALIFYING_VOLUME_USD = 100_000.0
INITIAL_POOL_UNLOCK_VOLUME_USD = 2_000_000.0
INITIAL_POOL_USD = 5_000.0
STEP_VOLUME_USD = 400_000.0
STEP_REWARD_USD = 1_000.0
MAX_POOL_USD = 50_000.0


@dataclass(frozen=True)
class CampaignEconomicsSummary:
    aggregate_qualifying_volume_usd: float
    funded_prize_pool_usd: float
    product_qualifying_volume_usd: float
    is_product_eligible: bool
    partner_direct_revenue_usd: float
    estimated_prize_award_usd: float
    total_partner_earnings_usd: float


def calculate_funded_prize_pool(aggregate_qualifying_volume_usd: float) -> float:
    """
    Calculates the funded MultiHopper competition prize pool from aggregate qualifying volume:
    - $2,000,000 aggregate qualifying volume unlocks the initial $5,000 pool
    - Every additional $400,000 unlocks another $1,000
      ($4M -> $10,000; $8M -> $20,000; $11M -> $27,000; $20M -> $50,000 max cap)
    """
    if aggregate_qualifying_volume_usd < INITIAL_POOL_UNLOCK_VOLUME_USD:
        return 0.0
    extra_volume = max(0.0, aggregate_qualifying_volume_usd - INITIAL_POOL_UNLOCK_VOLUME_USD)
    steps = int(extra_volume // STEP_VOLUME_USD)
    pool = INITIAL_POOL_USD + (steps * STEP_REWARD_USD)
    return float(min(MAX_POOL_USD, pool))


def allocate_top_three_prizes(
    team_volumes_usd: Dict[str, float],
    aggregate_qualifying_volume_usd: float,
) -> Dict[str, float]:
    """
    Filters eligible products (>= $100,000 qualifying volume), takes the top 3 by qualifying volume,
    and allocates the funded pool proportionally:
    Your prize = total funded pool * your qualifying volume / combined qualifying volume of the top three.
    """
    eligible = {
        team: vol
        for team, vol in team_volumes_usd.items()
        if vol >= MIN_PRODUCT_QUALIFYING_VOLUME_USD
    }
    if not eligible:
        return {team: 0.0 for team in team_volumes_usd}

    pool = calculate_funded_prize_pool(aggregate_qualifying_volume_usd)
    if pool <= 0.0:
        return {team: 0.0 for team in team_volumes_usd}

    top_three = sorted(eligible.items(), key=lambda kv: kv[1], reverse=True)[:3]
    combined_top_three_volume = sum(v for _, v in top_three)

    awards: Dict[str, float] = {team: 0.0 for team in team_volumes_usd}
    if combined_top_three_volume <= 0:
        return awards

    for team, vol in top_three:
        awards[team] = round(pool * (vol / combined_top_three_volume), 2)
    return awards


def evaluate_product_economics(
    product_qualifying_volume_usd: float,
    other_top_competitors_volume_usd: List[float],
    aggregate_campaign_volume_usd: float,
) -> CampaignEconomicsSummary:
    is_eligible = product_qualifying_volume_usd >= MIN_PRODUCT_QUALIFYING_VOLUME_USD
    partner_revenue = round(product_qualifying_volume_usd * 0.0025, 2)
    teams = {"our_product": product_qualifying_volume_usd}
    for i, v in enumerate(other_top_competitors_volume_usd):
        teams[f"competitor_{i+1}"] = v

    total_agg = max(
        aggregate_campaign_volume_usd,
        sum(teams.values()),
    )
    pool = calculate_funded_prize_pool(total_agg)
    awards = allocate_top_three_prizes(teams, total_agg)
    our_prize = awards.get("our_product", 0.0)

    return CampaignEconomicsSummary(
        aggregate_qualifying_volume_usd=total_agg,
        funded_prize_pool_usd=pool,
        product_qualifying_volume_usd=product_qualifying_volume_usd,
        is_product_eligible=is_eligible,
        partner_direct_revenue_usd=partner_revenue,
        estimated_prize_award_usd=our_prize,
        total_partner_earnings_usd=round(partner_revenue + our_prize, 2),
    )
