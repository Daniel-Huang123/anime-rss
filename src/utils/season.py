"""季度工具函数：计算当前季度、季度转换、N季度前等。

季度定义：
  Q1 → 1月   Q2 → 4月   Q3 → 7月   Q4 → 10月
"""

from datetime import date


# 每个季度对应的起始月份
QUARTER_MONTHS = {1: 1, 2: 4, 3: 7, 4: 10}
MONTH_TO_QUARTER = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2,
                    7: 3, 8: 3, 9: 3, 10: 4, 11: 4, 12: 4}


def current_quarter() -> str:
    """返回当前季度字符串，如 '2026Q1'。"""
    today = date.today()
    q = MONTH_TO_QUARTER[today.month]
    return f"{today.year}Q{q}"


def quarter_to_ym(quarter: str) -> tuple[int, int]:
    """将季度字符串转为 (year, month)。
    例：'2026Q1' → (2026, 1)，'2026Q3' → (2026, 7)
    """
    year, q = int(quarter[:4]), int(quarter[5])
    return year, QUARTER_MONTHS[q]


def ym_to_quarter(year: int, month: int) -> str:
    """将 (year, month) 转为季度字符串。"""
    q = MONTH_TO_QUARTER[month]
    return f"{year}Q{q}"


def quarters_ago(n: int, base: str | None = None) -> str:
    """返回 base 季度往前数 n 个季度的字符串。
    base 为 None 时使用当前季度。
    例：quarters_ago(2, '2026Q1') → '2025Q3'
    """
    base = base or current_quarter()
    year, month = quarter_to_ym(base)
    # 转为季度序号（从1开始的全局序号）
    total_quarters = year * 4 + MONTH_TO_QUARTER[month] - 1
    total_quarters -= n
    new_year = total_quarters // 4
    new_q = total_quarters % 4 + 1
    return f"{new_year}Q{new_q}"


def all_quarters_since(start: str, end: str | None = None) -> list[str]:
    """返回 [start, end] 区间内所有季度（含首尾），按时间升序。"""
    end = end or current_quarter()
    result = []
    cur = start
    while True:
        result.append(cur)
        if cur == end:
            break
        year, month = quarter_to_ym(cur)
        total = year * 4 + MONTH_TO_QUARTER[month] - 1
        total += 1
        cur = f"{total // 4}Q{total % 4 + 1}"
        if len(result) > 50:  # 安全上限
            break
    return result


def list_season_options(count: int = 6) -> list[str]:
    """返回最近 count 个季度列表（当前季度排在最前），供下拉框使用。"""
    return [quarters_ago(i) for i in range(count)]
