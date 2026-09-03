"""Prefixes shared by the Playground-derived rate-rule writers."""

# The BNGL writer and the reverse SBML writer must recognize the same
# synthetic names. Keep the source-defined prefixes in one module so a later
# writer port cannot silently change only one side of the round trip.
RATE_RULE_META_PREFIX = "__rate_rule__"
SYNTH_RATE_RULE_SPECIES_PREFIX = "__rate_rule_state__"

# The TypeScript BNGL writer keeps these directional prefixes beside its
# writer implementation. They are centralized here because the Python writer
# emits the same source/sink pair.
RATE_RULE_POS_PREFIX = "__rate_rule_pos__"
RATE_RULE_NEG_PREFIX = "__rate_rule_neg__"

__all__ = [
    "RATE_RULE_META_PREFIX",
    "RATE_RULE_NEG_PREFIX",
    "RATE_RULE_POS_PREFIX",
    "SYNTH_RATE_RULE_SPECIES_PREFIX",
]
