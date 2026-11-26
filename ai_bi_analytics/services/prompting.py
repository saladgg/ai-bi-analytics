"""
Helpers for building prompts that keep untrusted text separate from
instructions (audit SEC-6).

Untrusted content (the user's question, database rows) goes inside a
named tag in the *user* message; the rules live in the *system* message
and tell the model that tagged content is data. Any copy of the tag in
the content is removed so it can't close the block early and smuggle
text outside it.

This is a cost and accuracy measure, not the security boundary: the SQL
guard and the read-only database role are what stop a hostile query.
"""

import re


def untrusted_block(tag: str, text: str) -> str:
    cleaned = re.sub(rf"<\s*/?\s*{re.escape(tag)}\b[^>]*>", "", text, flags=re.I)
    return f"<{tag}>\n{cleaned}\n</{tag}>"
