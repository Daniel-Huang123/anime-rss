"""季度工具函数单元测试。"""

import pytest
from src.utils.season import (
    current_quarter,
    quarter_to_ym,
    ym_to_quarter,
    quarters_ago,
    all_quarters_since,
    list_season_options,
)


def test_quarter_to_ym():
    assert quarter_to_ym("2026Q1") == (2026, 1)
    assert quarter_to_ym("2026Q2") == (2026, 4)
    assert quarter_to_ym("2026Q3") == (2026, 7)
    assert quarter_to_ym("2026Q4") == (2026, 10)


def test_ym_to_quarter():
    assert ym_to_quarter(2026, 1) == "2026Q1"
    assert ym_to_quarter(2026, 2) == "2026Q1"
    assert ym_to_quarter(2026, 3) == "2026Q1"
    assert ym_to_quarter(2026, 4) == "2026Q2"
    assert ym_to_quarter(2026, 7) == "2026Q3"
    assert ym_to_quarter(2026, 10) == "2026Q4"
    assert ym_to_quarter(2026, 12) == "2026Q4"


def test_quarters_ago():
    assert quarters_ago(1, "2026Q1") == "2025Q4"
    assert quarters_ago(2, "2026Q1") == "2025Q3"
    assert quarters_ago(4, "2026Q1") == "2025Q1"
    assert quarters_ago(0, "2026Q2") == "2026Q2"


def test_quarters_ago_cross_year():
    assert quarters_ago(3, "2026Q2") == "2025Q3"
    assert quarters_ago(5, "2026Q1") == "2024Q4"


def test_all_quarters_since():
    qs = all_quarters_since("2025Q3", "2026Q2")
    assert qs == ["2025Q3", "2025Q4", "2026Q1", "2026Q2"]


def test_all_quarters_since_single():
    qs = all_quarters_since("2026Q1", "2026Q1")
    assert qs == ["2026Q1"]


def test_list_season_options():
    options = list_season_options(4)
    assert len(options) == 4
    # 第一个是当前季度
    assert options[0] == current_quarter()
    # 每个都是不同的季度
    assert len(set(options)) == 4


def test_current_quarter_format():
    q = current_quarter()
    assert len(q) == 6
    assert q[4] == "Q"
    assert q[5] in "1234"
    assert q[:4].isdigit()
