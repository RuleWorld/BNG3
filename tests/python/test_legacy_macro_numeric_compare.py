"""Source-derived regression for the legacy MacroBNGModel site-count test."""

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MACRO_MODEL = REPO / "legacy" / "perl" / "Perl2" / "MacroBNGModel.pm"


def test_macro_site_count_uses_numeric_comparison():
    """The dca95a6a source fix must not use Perl's lexicographic ``gt``."""

    source = MACRO_MODEL.read_text(encoding="utf-8")
    assert "if ( $key=~/:/ && $val > 1 ) { $nm2_site->{$key} = $val; }" in source
    assert "$val gt 1" not in source
