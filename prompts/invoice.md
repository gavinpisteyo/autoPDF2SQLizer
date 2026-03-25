# Invoice Extraction

Pay special attention to:
- The invoice number is often in the header, labeled "Invoice #", "Invoice No.", "Inv #", etc.
- Dates may appear in various formats (MM/DD/YYYY, DD/MM/YYYY, Month DD, YYYY) — always normalize to YYYY-MM-DD.
- Line items are usually in a table. Map columns carefully: "Qty" → quantity, "Rate"/"Price" → unit_price, "Amount"/"Total" → amount.
- The vendor is typically the company issuing the invoice (logo/letterhead at top).
- The customer is typically in the "Bill To" or "Ship To" section.
- Subtotal, tax, and total are usually at the bottom of the line items table.
- Currency can often be inferred from the symbol ($, €, £) if not stated explicitly.
