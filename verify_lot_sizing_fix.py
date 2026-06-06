#!/usr/bin/env python3
"""Verify lot-sizing fix works correctly."""

from agent.core.futures_utils import entry_lots_from_portfolio_margin

# Test: ₹15,740 cash, 60% budget, 5x leverage, BTC $100k
available_cash_inr = 15_740.58
portfolio_value_inr = available_cash_inr  # Fix 1: use real cash
usdinr_rate = 85.0
btc_price = 100_000.0
leverage = 5
cv = 0.001
margin_frac = 0.60
fee_reserve = 0.02

lots, margin_used = entry_lots_from_portfolio_margin(
    portfolio_value_inr=portfolio_value_inr,
    margin_fraction=margin_frac,
    usdinr_rate=usdinr_rate,
    btc_price=btc_price,
    leverage=leverage,
    contract_value_btc=cv,
    max_lots=100,
    min_lots=1,
    available_cash_inr=available_cash_inr,
    fee_reserve_fraction=fee_reserve,
    taker_fee_rate=0.0005,
    slippage_bps=5.0,
)

cash_remaining = available_cash_inr - margin_used
reserve_floor = available_cash_inr * 0.40
budget_target = portfolio_value_inr * margin_frac

print("\n=== JackSparrow Lot-Sizing Verification ===\n")
print(f"Available cash:      INR {available_cash_inr:>12,.2f}")
print(f"60% budget target:   INR {budget_target:>12,.2f}")
print(f"Lots sized:          {lots:>18} (expected 5)")
print(f"Margin used:         INR {margin_used:>12,.2f}")
print(f"Cash remaining:      INR {cash_remaining:>12,.2f} ({cash_remaining/available_cash_inr*100:>5.1f}%)")
print(f"Reserve floor (40%): INR {reserve_floor:>12,.2f}")
status = "PASS ✓" if cash_remaining >= reserve_floor else "FAIL ✗"
print(f"Reserve check:       {status}")

# Detailed check
print(f"\nExpectations (from attachment):")
print(f"  Lots: 5          | Got: {lots}  | {'✓' if lots == 5 else '✗'}")
print(f"  Margin ~54% of wallet | Got: {margin_used/available_cash_inr*100:.1f}%  | {'✓' if 50 <= margin_used/available_cash_inr*100 <= 60 else '✗'}")
print(f"  Remaining ~46%   | Got: {cash_remaining/available_cash_inr*100:.1f}%  | {'✓' if 40 <= cash_remaining/available_cash_inr*100 <= 50 else '✗'}")

if lots == 5 and cash_remaining >= reserve_floor:
    print("\n✓ BOTH FIXES ARE WORKING - LOT SIZING CORRECT\n")
else:
    print(f"\n✗ LOT SIZING MISMATCH - FIXES NEED REVIEW\n")
