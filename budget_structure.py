"""Single source of truth for the budget line item structure.

The web admin budget page, the Telegram inline keyboards and the Telegram
text-format validator all read from here, so they cannot drift.

That drift is not hypothetical: the previous Telegram bot (removed in
commit 0d41a42) kept its own copy that had been edited independently and ended up
with 'Service/Maintainance', 'Colletrals' and a 'Payroll & Pilotage fee' category.
It wrote actuals under names the budget page never rendered, so those numbers
were invisible. Import these names instead of re-typing them.

Keeping this module free of Flask, database and network imports also lets the
Telegram keyboard builders and their tests import it cheaply.
"""

FINANCIAL_STRUCTURE = {
    "Other Expenses": [
        "Power",
        "Water",
        "IT",
        "Communication",
        "Stationery",
        "Service/Maintenance",
        "Misc",
        "Other",
    ],
    "Promotion Expenses": [
        "Marketing",
        "Promotions",
        "Collaterals",
        "Printing/Advertising",
        "Travel",
        "Transportation",
    ],
    "Payroll & Pilotage": [
        "Pilotage",
        "Payroll",
        "Misc",
        "Other",
    ],
    "Fixed Costs": [
        "Rent",
        "Tax",
    ],
}

MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

# 'Misc' and 'Other' appear in more than one category, so an actual recorded
# against them cannot be attributed to a single category. budget_actuals_cache
# is keyed by line item name only, so both categories share one row.
SHARED_LINE_ITEMS = frozenset(
    item
    for item in {i for items in FINANCIAL_STRUCTURE.values() for i in items}
    if sum(item in items for items in FINANCIAL_STRUCTURE.values()) > 1
)
