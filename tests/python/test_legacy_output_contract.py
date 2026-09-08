"""Source-derived regression for legacy diagnostic/output contracts."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ACTION = REPO / "legacy" / "perl" / "Perl2" / "BNGAction.pm"
OUTPUT = REPO / "legacy" / "perl" / "Perl2" / "BNGOutput.pm"


def test_legacy_simulate_nf_diagnostic_uses_retrieve_spelling():
    """The dca95a6a source diagnostic must not retain its typo."""

    source = ACTION.read_text(encoding="utf-8")
    assert "To retrieve system state" in source
    assert "To retreive system state" not in source


def test_legacy_output_has_checked_query_names_open_and_correct_ssc_message():
    """The dca95a6a output fixes must remain explicit in the legacy writer."""

    source = OUTPUT.read_text(encoding="utf-8")
    assert 'print STDOUT "\\n Writing SSC cfg file \\n";' in source
    assert "Writting SSC cfg file" not in source
    assert (
        "open( Q_Mscript, '>', $q_mscript )\n"
        '        or return "Couldn\'t open $q_mscript for writing: $!\\n";'
    ) in source
    assert "the nanmes of all species" not in source
    assert "the names of all species" in source
    assert "the names of the seed species" in source
    assert "the names of the seed speceis" not in source
