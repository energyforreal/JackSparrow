"""Analytics API routes for trade optimization."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.services.analytics_service import analytics_service

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid date: {exc}",
        ) from exc


@router.get("/trade-outcomes")
async def get_trade_outcomes(
    symbol: Optional[str] = Query(None),
    regime: Optional[str] = Query(None),
    setup_type: Optional[str] = Query(None),
    close_reason: Optional[str] = Query(None),
    config_hash: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Paginated closed trades with full decision snapshot metadata."""
    return await analytics_service.list_trade_outcomes(
        db,
        symbol=symbol,
        regime=regime,
        setup_type=setup_type,
        close_reason=close_reason,
        config_hash=config_hash,
        from_date=_parse_dt(from_date),
        to_date=_parse_dt(to_date),
        limit=limit,
        offset=offset,
    )


@router.get("/entry-decisions")
async def get_entry_decisions(
    symbol: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Approval funnel and rejection reason breakdown."""
    return await analytics_service.entry_decision_funnel(
        db,
        symbol=symbol,
        from_date=_parse_dt(from_date),
        to_date=_parse_dt(to_date),
    )


@router.get("/performance-by-regime")
async def get_performance_by_regime(
    symbol: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Win rate and PnL grouped by market regime."""
    return await analytics_service.performance_by_regime(
        db,
        symbol=symbol,
        from_date=_parse_dt(from_date),
        to_date=_parse_dt(to_date),
    )


@router.get("/performance-by-config")
async def get_performance_by_config(
    symbol: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Compare performance across config_hash cohorts."""
    return await analytics_service.performance_by_config(db, symbol=symbol)


@router.get("/rollups")
async def get_rollups(
    period_type: Optional[str] = Query(None),
    symbol: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Precomputed daily/weekly/regime/setup/config rollups."""
    return await analytics_service.list_rollups(
        db,
        period_type=period_type,
        symbol=symbol,
        limit=limit,
    )


@router.get("/attribution-summary")
async def get_attribution_summary(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Root cause and four-dimension quality breakdown."""
    return await analytics_service.attribution_summary(
        db,
        from_date=_parse_dt(from_date),
        to_date=_parse_dt(to_date),
    )


@router.get("/trade-quality")
async def get_trade_quality(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Entry/execution/exit/market quality distributions."""
    return await analytics_service.trade_quality_distribution(
        db,
        from_date=_parse_dt(from_date),
        to_date=_parse_dt(to_date),
    )


@router.get("/regime-benchmarks")
async def get_regime_benchmarks(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Performance grouped by regime_benchmark label."""
    return await analytics_service.regime_benchmark_performance(
        db,
        from_date=_parse_dt(from_date),
        to_date=_parse_dt(to_date),
    )


@router.get("/rule-evaluation")
async def get_rule_evaluation(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Per-rule stats, interactions, and FP/FN counts."""
    return await analytics_service.rule_evaluation_report(
        db,
        from_date=_parse_dt(from_date),
        to_date=_parse_dt(to_date),
    )


@router.get("/confidence-calibration")
async def get_confidence_calibration(
    from_date: Optional[str] = Query(None),
    to_date: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    """Structural confidence bucket vs actual win rate."""
    return await analytics_service.confidence_calibration(
        db,
        from_date=_parse_dt(from_date),
        to_date=_parse_dt(to_date),
    )
