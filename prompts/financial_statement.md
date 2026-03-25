# Financial Statement Extraction

Pay special attention to:
- Determine the statement_type: "income_statement" (P&L), "balance_sheet", or "cash_flow".
- Period dates may be expressed as "For the year ended December 31, 2024" or "As of March 31, 2025".
- Numbers may be in thousands or millions — look for notes like "(in thousands)" or "($ millions)" and multiply accordingly.
- Parentheses around numbers typically mean negative values: (1,234) = -1234.
- Revenue may be labeled "Net Sales", "Total Revenue", "Net Revenue", etc.
- Net income may be labeled "Net Income", "Net Profit", "Net Earnings", "Profit for the Period", etc.
- Balance sheet fields (total_assets, total_liabilities, total_equity) may not be present on income statements — use null.
