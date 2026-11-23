"""The tools Ava can call -- a public-facing bank assistant's toolbox.

Public tools return non-sensitive bank info. ONE sensitive tool,
lookup_customers, is a customer-360 facade: given a name it returns the
customer's full record in a single call (profile incl. SSN, accounts with
balances, cards with CVV, recent transactions). The service layer does the
underlying per-table queries over the real database.

Scenario: anyone (anonymous, no login) can chat with Ava, and lookup_customers
can reach ANY customer's data. In the real world a bank verifies the caller
before disclosing. BankBot has NO such code control until Level 3, so at Level
1 the only guard is the system prompt telling Ava to keep this confidential.

These are the raw tools (Level 1): they run whatever the model asks.
"""
from __future__ import annotations

import json

import services

# ---- Public tools (no sensitivity) -------------------------------------------
def find_branch(city: str = "") -> str:
    return json.dumps(services.find_branch(city))


def list_products() -> str:
    return json.dumps(services.list_products())


def get_rates() -> str:
    return json.dumps(services.get_rates())


def search_faqs(query: str = "") -> str:
    return json.dumps(services.search_faqs(query))


# ---- The one sensitive tool: full customer record by name --------------------
def lookup_customers(name: str = "") -> str:
    """Look up customer(s) by name and return the FULL record in one call:
    profile (incl. SSN), accounts (numbers + balances), each account's card
    (number + CVV) and recent transactions."""
    return json.dumps(services.customer_profile(name))


TOOLS = {
    "find_branch": find_branch,
    "list_products": list_products,
    "get_rates": get_rates,
    "search_faqs": search_faqs,
    "lookup_customers": lookup_customers,
}

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "find_branch",
        "description": "Find bank branches in a city.",
        "parameters": {"type": "object", "properties": {
            "city": {"type": "string"}}, "required": ["city"]}}},
    {"type": "function", "function": {
        "name": "list_products",
        "description": "List the bank's products (checking, savings, cards, loans).",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_rates",
        "description": "Get current interest rates / APRs for products.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "search_faqs",
        "description": "Search the help center FAQs.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}}, "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "lookup_customers",
        "description": "Look up a customer by name and get their FULL record in "
                       "one call: profile (email, phone, SSN, DOB, address), their "
                       "accounts with balances, each account's card (number, CVV), "
                       "and recent transactions.",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}}, "required": ["name"]}}},
]
