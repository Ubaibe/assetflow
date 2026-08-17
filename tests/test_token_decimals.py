import pytest
from decimal import Decimal, InvalidOperation

from services.token_decimals import (
    TokenDecimalError,
    get_token_decimals,
    to_base_units,
    from_base_units,
)


def test_default_decimals_is_18():
    assert get_token_decimals() == 18


def test_decimals_from_config():
    assert get_token_decimals({"PAYMENT_TOKEN_DECIMALS": "6"}) == 6
    assert get_token_decimals({"PAYMENT_TOKEN_DECIMALS": 18}) == 18


def test_decimals_rejects_negative():
    with pytest.raises(TokenDecimalError, match="cannot be negative"):
        get_token_decimals({"PAYMENT_TOKEN_DECIMALS": "-1"})


def test_decimals_rejects_non_integer():
    with pytest.raises(TokenDecimalError, match="must be an integer"):
        get_token_decimals({"PAYMENT_TOKEN_DECIMALS": "abc"})


def test_18_decimal_conversion_exact():
    result = to_base_units(Decimal("100.50"), 18)
    assert result == 100500000000000000000
    assert isinstance(result, int)


def test_6_decimal_conversion_exact():
    result = to_base_units(Decimal("100.50"), 6)
    assert result == 100500000
    assert isinstance(result, int)


def test_6_decimal_rejects_excess_precision():
    with pytest.raises(TokenDecimalError, match="cannot be represented exactly"):
        to_base_units(Decimal("100.1234567"), 6)


def test_18_decimal_rejects_excess_precision():
    with pytest.raises(TokenDecimalError, match="cannot be represented exactly"):
        to_base_units(Decimal("100.1234567890123456789"), 18)


def test_zero_amount_rejected():
    with pytest.raises(TokenDecimalError, match="must be greater than zero"):
        to_base_units(Decimal("0"), 18)


def test_negative_amount_rejected():
    with pytest.raises(TokenDecimalError, match="must be greater than zero"):
        to_base_units(Decimal("-10"), 18)


def test_none_amount_rejected():
    with pytest.raises(TokenDecimalError, match="cannot be None"):
        to_base_units(None, 18)


def test_from_base_units_18_decimal():
    result = from_base_units(100500000000000000000, 18)
    assert result == Decimal("100.50")


def test_from_base_units_6_decimal():
    result = from_base_units(100500000, 6)
    assert result == Decimal("100.50")


def test_from_base_units_rejects_negative():
    with pytest.raises(TokenDecimalError, match="cannot be negative"):
        from_base_units(-1, 18)


def test_no_float_arithmetic_used():
    result = to_base_units(Decimal("0.01"), 6)
    assert isinstance(result, int)
    assert result == 10000
    assert type(result) is int


def test_integer_string_amount_accepted():
    result = to_base_units("100", 18)
    assert result == 100000000000000000000


def test_invalid_string_amount_rejected():
    with pytest.raises(TokenDecimalError, match="Invalid amount"):
        to_base_units("not-a-number", 18)
