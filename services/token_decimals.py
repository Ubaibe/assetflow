from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


class TokenDecimalError(Exception):
    pass


def get_token_decimals(config: dict[str, Any] | None = None) -> int:
    if config is None:
        return 18
    decimals = config.get("PAYMENT_TOKEN_DECIMALS")
    if decimals is None:
        return 18
    try:
        value = int(decimals)
    except (TypeError, ValueError) as exc:
        raise TokenDecimalError("PAYMENT_TOKEN_DECIMALS must be an integer") from exc
    if value < 0:
        raise TokenDecimalError("Token decimals cannot be negative")
    return value


def to_base_units(human_amount: Decimal | int | str | None, decimals: int) -> int:
    if human_amount is None:
        raise TokenDecimalError("Amount cannot be None")
    if decimals < 0:
        raise TokenDecimalError("Token decimals cannot be negative")

    try:
        decimal_amount = Decimal(str(human_amount))
    except (InvalidOperation, ValueError) as exc:
        raise TokenDecimalError(f"Invalid amount: {human_amount}") from exc

    if decimal_amount <= 0:
        raise TokenDecimalError("Amount must be greater than zero")

    factor = Decimal(10) ** decimals
    result = decimal_amount * factor

    if result != result.to_integral_value():
        raise TokenDecimalError(
            f"Amount {human_amount} cannot be represented exactly with {decimals} decimals"
        )

    return int(result)


def from_base_units(base_units: int | None, decimals: int) -> Decimal:
    if base_units is None:
        raise TokenDecimalError("Base units cannot be None")
    if base_units < 0:
        raise TokenDecimalError("Base units cannot be negative")
    if decimals < 0:
        raise TokenDecimalError("Token decimals cannot be negative")

    factor = Decimal(10) ** decimals
    return Decimal(base_units) / factor
