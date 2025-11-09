#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ------------------------------------------------------------------------------
#
#   Copyright 2025 Valory AG
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
#
# ------------------------------------------------------------------------------

"""
This module contains the utils for calculating the sell amount.
Inspired by: https://github.com/SwaprHQ/presagio/blob/main/utils/price.ts
"""

from decimal import Decimal, getcontext, ROUND_HALF_UP
from typing import Iterable, Optional, Sequence, Union, Callable


NumberLike = Union[int, str, Decimal]


def _to_decimal(value: NumberLike) -> Decimal:
	"""Convert a number-like value to Decimal safely."""
	if isinstance(value, Decimal):
		return value
	# Use str to avoid float binary representation issues
	return Decimal(str(value))


def _product(values: Iterable[Decimal]) -> Decimal:
	"""Compute the product of iterable of Decimals."""
	result = Decimal(1)
	for v in values:
		result *= v
	return result


def _newton_raphson(
	f: Callable[[Decimal], Decimal],
	x0: Decimal,
	max_iterations: int = 100,
	tol: Decimal = Decimal("1e-60"),
) -> Optional[Decimal]:
	"""Generic Newton-Raphson root finder with numerical derivative."""
	# Numerical derivative step relative to magnitude of x
	def deriv(x: Decimal) -> Decimal:
		# Choose a small step proportional to |x|, but with a minimum
		h = max(Decimal("1e-24"), abs(x) * Decimal("1e-12"))
		return (f(x + h) - f(x - h)) / (h * 2)

	x = x0
	for _ in range(max_iterations):
		y = f(x)
		if abs(y) <= tol:
			return x
		dy = deriv(x)
		# Guard against zero derivative
		if dy == 0:
			return None
		x_next = x - y / dy
		# If the update is tiny, consider it converged
		if abs(x_next - x) <= tol:
			return x_next
		x = x_next
	return None


def calc_sell_amount_in_collateral(
	shares_to_sell_amount: NumberLike,
	market_shares_amounts: Sequence[NumberLike],
	selling_outcome_index: int,
	market_fee: float,
	max_iterations: int = 100,
) -> Optional[int]:
	"""
	Approximate the amount of collateral that will be returned for selling `shares_to_sell_amount` outcome shares.

	The computation mirrors the fixed product market maker relation used in the TS implementation:
	  For outcomes where the selling outcome is denoted as X and others as Y, Z, ...
	  f(r) = P_i (S_i - R) * (X + A - R) - (P_i S_i) = 0
	  where:
	    - r is the unknown collateral returned
	    - R = r / (1 - fee)
	    - X is current market shares of the selling outcome
	    - {S_i} are current market shares of the non-selling outcomes
	    - A is the amount of shares being sold

	Returns:
	  - int rounded to nearest integer (like toFixed(0) -> BigInt in TS) if convergence succeeds
	  - None if it couldn't be computed
	"""
	# High precision similar to Big.DP = 90 in TS. Decimal uses significant digits precision.
	ctx = getcontext()
	ctx.prec = 90
	ctx.rounding = ROUND_HALF_UP

	if not (0 <= market_fee < 1):
		return None
	if selling_outcome_index < 0 or selling_outcome_index >= len(market_shares_amounts):
		return None
	if len(market_shares_amounts) < 2:
		return None

	shares_to_sell = _to_decimal(shares_to_sell_amount)
	market_shares_decimals = [_to_decimal(v) for v in market_shares_amounts]

	market_selling_shares = market_shares_decimals[selling_outcome_index]
	non_selling_shares = [
		v for idx, v in enumerate(market_shares_decimals) if idx != selling_outcome_index
	]

	one_minus_fee = Decimal(1) - _to_decimal(market_fee)
	if one_minus_fee <= 0:
		return None

	def f(r: Decimal) -> Decimal:
		# R = r / (1 - fee)
		R = r / one_minus_fee
		# ((y - R) * (z - R) * ...)
		first_term = _product((h - R for h in non_selling_shares))
		# (x + a - R)
		second_term = market_selling_shares + shares_to_sell - R
		# (x * y * z * ...)
		third_term = _product(non_selling_shares) * market_selling_shares
		return first_term * second_term - third_term

	# Start from 0 as in the TS implementation
	root = _newton_raphson(f, Decimal(0), max_iterations=max_iterations)
	if root is None:
		return None
	# Round to nearest integer (toFixed(0) semantics)
	rounded = root.quantize(Decimal(1), rounding=ROUND_HALF_UP)
	# Ensure non-negative result
	if rounded < 0:
		return None
	return int(rounded)

