from __future__ import annotations

from typing import TYPE_CHECKING

from deltona.adp import SalaryResponse, calculate_salary
from niquests.exceptions import HTTPError
import pytest

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test_salary_response_str() -> None:
    response = SalaryResponse(federal=100.0,
                              fica=50.0,
                              fuckery=175.0,
                              gross=1000.0,
                              medicare=25.0,
                              net_pay=825.0,
                              state=0)
    expected_str = """Gross     \033[1;32m 1000.00\033[0m
Federal   \033[1;32m  100.00\033[0m
FICA      \033[1;32m   50.00\033[0m
Medicare  \033[1;32m   25.00\033[0m
State     \033[1;32m    0.00\033[0m
------------------
Net       \033[1;32m  825.00\033[0m

------------------
Fuckery   \033[1;31m  175.00\033[0m"""
    assert str(response) == expected_str


FEDERAL_TAX = 100.0
FICA_TAX = 50.0
GROSS_PAY = 4900.0
MEDICARE_TAX = 25.0
NET_PAY = 825.0
STATE = 0
FUCKERY = 175.0


@pytest.mark.asyncio
async def test_calculate_salary_success(mocker: MockerFixture) -> None:
    mock_response = mocker.Mock()
    mock_response.json.return_value = {
        'content': {
            'federal': 100.0,
            'fica': 50.0,
            'medicare': 25.0,
            'netPay': 825.0,
            'state': 0
        }
    }
    mock_response.raise_for_status = mocker.Mock()
    mock_session = mocker.MagicMock()
    mock_session.post = mocker.AsyncMock(return_value=mock_response)
    mock_async_session = mocker.patch('deltona.adp.AsyncSession')
    mock_async_session.return_value.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = mocker.AsyncMock(return_value=False)
    result = await calculate_salary(hours=70, pay_rate=70.0, state='FL')

    assert result.federal == FEDERAL_TAX
    assert result.fica == FICA_TAX
    assert result.medicare == MEDICARE_TAX
    assert result.net_pay == NET_PAY
    assert result.state == STATE
    assert result.gross == GROSS_PAY


@pytest.mark.asyncio
async def test_calculate_salary_http_error(mocker: MockerFixture) -> None:
    mock_response = mocker.Mock()
    mock_response.raise_for_status.side_effect = HTTPError
    mock_session = mocker.MagicMock()
    mock_session.post = mocker.AsyncMock(return_value=mock_response)
    mock_async_session = mocker.patch('deltona.adp.AsyncSession')
    mock_async_session.return_value.__aenter__ = mocker.AsyncMock(return_value=mock_session)
    mock_async_session.return_value.__aexit__ = mocker.AsyncMock(return_value=False)
    with pytest.raises(HTTPError):
        await calculate_salary(hours=70, pay_rate=70.0, state='FL')
