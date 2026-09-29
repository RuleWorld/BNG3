"""Small helpers shared by BNG3 BNGL benchmark harnesses."""

import re


def strip_bngl_action_blocks(source: str) -> str:
    """Remove executable actions before operating on a model's initial state."""
    output = []
    in_actions = False
    for line in source.splitlines(keepends=True):
        stripped = line.strip()
        if not in_actions and re.fullmatch(r"begin\s+actions", stripped, re.I):
            in_actions = True
            continue
        if in_actions:
            if re.fullmatch(r"end\s+actions", stripped, re.I):
                in_actions = False
            continue
        if re.fullmatch(r"end\s+actions", stripped, re.I):
            raise ValueError("BNGL has an end actions without a matching begin")
        output.append(line)
    if in_actions:
        raise ValueError("BNGL has an unterminated actions block")
    return "".join(output)
