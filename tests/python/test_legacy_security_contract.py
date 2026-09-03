"""Source-derived security contract for bundled BNG2 MacroBNGModel."""

from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]
MACRO_MODEL = REPO / "legacy" / "perl" / "Perl2" / "MacroBNGModel.pm"


# The final tree at Sentinel commit cdbd6ee9 is an empty duplicate of
# 2b95afe9.  The expected calls below are the security payload from 2b95afe9,
# combined with the already-landed .rab diagnostic fix from b13533cc.
EXPECTED_EXPLICIT_OPEN_CALLS = (
    ("WFILEbngl", ">", "$file"),
    ("WFILErec", ">", "$recfile"),
    ("WFILEpar", ">", "$parfile"),
    ("FH", "<", "$bnglfile"),
    ("WFILEpar", ">", "$parfile"),
    ("WFILEmacr", ">", "$macrfile"),
    ("RFILEpar", "<", "$parfile"),
    ("RFILEspec2", "<", "$spec2file"),
    ("RFILErules", "<", "$rulesfile"),
    ("RFILEobser", "<", "$obserfile"),
    ("WFILErules", ">", "$rulesfile"),
    ("RFILErec", "<", "$recfile"),
    ("WFILEobser", ">", "$obserfile"),
    ("WFILEspec2", ">", "$spec2file"),
)


def _explicit_open_pattern(handle: str, mode: str, path: str) -> re.Pattern[str]:
    return re.compile(
        rf"open\s*\(\s*{re.escape(handle)}\s*,\s*"
        rf"{re.escape(chr(34) + mode + chr(34))}\s*,\s*"
        rf"{re.escape(path)}\s*\)"
    )


def test_legacy_macro_uses_explicit_open_modes_for_all_file_paths():
    source = MACRO_MODEL.read_text(encoding="utf-8")

    missing = [
        (handle, mode, path)
        for handle, mode, path in EXPECTED_EXPLICIT_OPEN_CALLS
        if not _explicit_open_pattern(handle, mode, path).search(source)
    ]
    assert not missing, f"missing explicit-mode open calls: {missing}"

    forbidden = (
        'open (WFILEbngl, ">$file")',
        "open (WFILErec, $recfile)",
        "open (WFILEpar, $parfile)",
        "open(FH, $bnglfile)",
        "open (WFILEmacr, $macrfile)",
        "open (RFILEpar, $parfile)",
        "open (RFILEspec2, $spec2file)",
        "open (RFILErules, $rulesfile)",
        "open (RFILEobser, $obserfile)",
        "open (WFILErules, $rulesfile)",
        "open (RFILErec, $recfile)",
        "open (WFILEobser, $obserfile)",
        "open (WFILEspec2, $spec2file)",
    )
    present = [call for call in forbidden if call in source]
    assert not present, f"filename-controlled open modes remain: {present}"

    assert 'open (WFILErab, ">", $rabfile)' in source
    assert 'die "Can\'t open $rabfile: $!\\n"' in source


def test_legacy_macro_removes_mode_prefixes_from_path_variables():
    source = MACRO_MODEL.read_text(encoding="utf-8")

    forbidden_assignments = (
        '$bnglfile= "<${param_prefix}.bngl"',
        '$recfile= ">macr_${param_prefix}.rec"',
        '$parfile= ">macr_${param_prefix}.par"',
        '$macrfile= ">macr_${param_prefix}.bngl"',
        '$parfile= "<macr_${param_prefix}.par"',
        '$spec2file= "<macr_${param_prefix}.spec2"',
        '$rulesfile= "<macr_${param_prefix}.rules"',
        '$obserfile= "<macr_${param_prefix}.obser"',
        '$recfile= "<macr_${param_prefix}.rec"',
        '$obserfile= ">macr_${param_prefix}.obser"',
        '$spec2file= ">macr_${param_prefix}.spec2"',
    )
    present = [
        assignment for assignment in forbidden_assignments if assignment in source
    ]
    assert not present, f"mode prefixes remain in path variables: {present}"
