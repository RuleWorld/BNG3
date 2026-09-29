"""Network-free parity.

Two directions, both required for WO-2:
  (a) ast-direct vs native NFsim binary   correctness of the merged engine
  (b) ast-direct vs in-memory-XML path    the migration is behavior-preserving

(b) is gated by an env flag the engine exposes during the WO-2 migration window
(BNG_NFSIM_FORCE_XML=1 forces the old in-memory-XML construction). When that
flag is unavailable both paths are identical and (b) is a no-op pass.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import subprocess
import sys

import pytest

from tests.validation import compare, corpus, oracle_nfsim, runner
from tests.validation.strict import require_oracle

NF_MODELS = [m for m in corpus.tier_nf()]

# --------------------------------------------------------------------------- #
# Tier-P direct-path sweep
# --------------------------------------------------------------------------- #
#
# test_nf_ast_direct_matches_xml above pins exact trajectory equality between
# the ast-direct and in-memory-XML construction routes, but it only ever ran
# over the four network-free models in tier-NF. The committed tier-P selection
# is 100 records (provenance/corpus/selection.json, tiers.p), and nothing in
# the harness ever asked the direct path what it does with the other 96.
#
# The nine-stage builder in cpp/nfsim/NFinput/NFinput_fromAst.cpp records a
# named stage and reason for every decline (:5999-6029), so a decline is a
# reportable measurement rather than a failure: no oracle and no native binary
# are needed to classify a model. This sweep therefore asserts two things.
#
#   accepted  the direct path constructs and runs the model, and under one
#             fixed seed its trajectory is bit-identical to in-memory-XML
#             (rtol=atol=0, exactly as the tier-NF comparison does)
#   declined  the direct path refused, and the refusal carries an attributed
#             cause. An unattributed decline fails, because
#             buildSystemFromAstWithSeedOverrides promises that every
#             `return nullptr` records why (NFinput_fromAst.cpp:5908-5918).
#
# A decline is not a regression and is not a failure. What would be a
# regression is a decline that has stopped naming its cause, or a model that
# used to be accepted and now runs on a different construction path than the
# comparison believes.
#
# Every model is probed in a child process. NFsim calls exit(1) from
# cpp/nfsim/NFcore/reactionClass.cpp:175 on a pattern it refuses outright, and
# several tier-P models abort there; in-process that would take pytest down
# instead of reporting a declined model.
#
# SWEEP_HORIZON is deliberately short. Acceptance is a property of the nine
# builder stages, all of which run before the first time step, so a short
# window measures the thing being counted. The expensive t_end=50 comparison
# stays where it was, on tier-NF, unchanged. Models slower than
# SWEEP_TIMEOUT_S are reported as incomplete, never as accepted.

SWEEP_SEED = 7
SWEEP_T_END = 0.1
SWEEP_N_STEPS = 10
SWEEP_TIMEOUT_S = 300
SWEEP_ARTIFACT = corpus.REPO / "build" / "validation" / "direct_path_sweep.json"

TIER_P_MODELS = list(corpus.tier_p())

# bind_nfsim composes this message as "<prefix>: <direct_unavailable_reason>;
# <suffix>" (cpp/bindings/bind_nfsim.cpp:117-130), so the attributed reason is
# recoverable from the fail-closed exception without enabling the XML fallback
# (which risks the NFsim aborts described above).
_DECLINE_PREFIX = "NFsim direct AST initialization unavailable: "
_DECLINE_SUFFIX = "; XML fallback disabled"

# Known seed-state-order divergences, tracked as a strict xfail.
#
# BUG (fixed in cpp/nfsim/NFinput/NFinput_fromCompiled.cpp, seed-species
# stage): the seed builder used `PatternStateConstraint::exact->index` -- an
# offset into the atomizer's *discovery order* for a component's allowed
# states -- directly as the NFsim state value.  NFsim's value is an offset
# into the molecule type's own state table, which addMoleculeTypesFromCompiled
# renumbers to 0..max for an all-integer component (the XML loader does the
# same, NFinput.cpp:585-591).  ANx declares `RD(...,m~2)` in its species
# block before any observable mentions `m~0`, so '2' is discovery index 0 and
# every seed receptor was created in NFsim state 0.  The observables were
# right all along; they were reporting a population that had been built in
# the wrong state, which is why `R0 RD(m~0)` returned the whole seed pool and
# `RD_R`/`RD_B` (which read that state through MethLevel) also diverged.
#
# These three models share the AN family and therefore the defect.  The
# marker is deliberately strict in both directions: a *new* divergence still
# fails the suite, and a listed model that stops diverging fails it too,
# because an xfail that quietly starts passing is exactly the failure this
# harness exists to prevent -- remove the name from this tuple instead.
_KNOWN_SEED_STATE_ORDER_DIVERGENCES: tuple = ()

# The child program. Kept as source text so the probe needs no file of its own.
_SWEEP_CHILD = """
import json, os, sys

sys.path.insert(0, os.getcwd())
sys.path.insert(0, os.path.join(os.getcwd(), "python"))

import numpy as np

from tests.validation import compare, corpus
import bionetgen

model_name, t_end, n_steps, seed = sys.argv[1], float(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])

# Fail closed: the direct leg must not be allowed to fall back, or a decline
# would silently become an in-memory-XML run and read as acceptance.
os.environ.pop("BNG_NFSIM_FORCE_XML", None)
os.environ.pop("BNG_NFSIM_ALLOW_XML_FALLBACK", None)
os.environ.pop("BNG_NFSIM_REQUIRE_DIRECT", None)

def run(model):
    # Built here rather than via runner.run_api: runner.Trajectory carries only
    # construction_path (tests/validation/runner.py), and the sweep needs
    # direct_unavailable_reason off the same result.
    source = corpus.resolve(model)
    if source is None:
        raise FileNotFoundError(f"model {model!r} not found on disk")
    return bionetgen.load(str(source)).simulate(
        method="nf", seed=seed, t_end=t_end, n_steps=n_steps
    )

def trajectory(result):
    # Same (n_t, n_col) layout runner._result_to_trajectory produces: column 0
    # is time, the rest are observables in dict order.
    time = np.asarray(result.time, dtype=float)
    obs = result.observables
    names = list(obs)
    data = np.column_stack([time] + [np.asarray(obs[n], float) for n in names])
    return data, ["time"] + names

record = {"model": model_name}
direct = None
try:
    direct = run(model_name)
except BaseException as exc:
    record["error"] = f"{type(exc).__name__}: {exc}"

if direct is not None:
    # The direct verdict is settled here and is independent of the XML leg: a
    # model the direct path accepts is accepted even if the comparison leg
    # later fails, and collapsing the two would misreport which one broke.
    # Every field is read before the verdict is recorded, so a probe bug can
    # never leave a half-filled record that reads as acceptance.
    construction_path = direct.construction_path
    unavailable_reason = direct.direct_unavailable_reason
    record["direct_status"] = "accepted"
    record["construction_path"] = construction_path
    record["direct_unavailable_reason"] = unavailable_reason
    try:
        os.environ["BNG_NFSIM_FORCE_XML"] = "1"
        os.environ["BNG_NFSIM_ALLOW_XML_FALLBACK"] = "1"
        xml = run(model_name)
        xml_path = xml.construction_path
        xml_data, xml_cols = trajectory(xml)
        direct_data, direct_cols = trajectory(direct)
        diff = compare.compare_trajectories(
            xml_data, xml_cols, direct_data, direct_cols, rtol=0.0, atol=0.0
        )
        record["xml_construction_path"] = xml_path
        record["max_rel_err"] = float(diff.max_rel_err)
        record["max_rel_col"] = diff.max_rel_col
        # The comparator reports "no shared observable columns" through its
        # note, with max_rel_err=inf. A model exposing no observables cannot be
        # compared on trajectories at all, which is a different fact from a
        # model whose observables disagree, so both are recorded.
        record["parity_note"] = diff.note
        record["direct_columns"] = [c for c in direct_cols if c != "time"]
        record["xml_columns"] = [c for c in xml_cols if c != "time"]
        record["parity_status"] = "compared"
    except BaseException as exc:
        record["parity_status"] = "unavailable"
        record["parity_error"] = f"{type(exc).__name__}: {exc}"

sys.stderr.write("@@sweep@@" + json.dumps(record) + "\\n")
"""


def _sweep_child(model_name: str) -> dict:
    """Probe one model in a child process; never raises for a declined model."""
    env = dict(os.environ)
    for name in (
        "BNG_NFSIM_FORCE_XML",
        "BNG_NFSIM_ALLOW_XML_FALLBACK",
        "BNG_NFSIM_REQUIRE_DIRECT",
    ):
        env.pop(name, None)
    argv = [
        sys.executable,
        "-c",
        _SWEEP_CHILD,
        model_name,
        str(SWEEP_T_END),
        str(SWEEP_N_STEPS),
        str(SWEEP_SEED),
    ]
    try:
        proc = subprocess.run(
            argv,
            cwd=str(corpus.REPO),
            env=env,
            capture_output=True,
            text=True,
            timeout=SWEEP_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return {"model": model_name, "status": "incomplete", "error": "timeout"}
    for line in proc.stderr.splitlines():
        if line.startswith("@@sweep@@"):
            return json.loads(line[len("@@sweep@@") :])
    tail = [ln for ln in (proc.stderr or proc.stdout or "").splitlines() if ln.strip()]
    return {
        "model": model_name,
        "status": "incomplete",
        "error": f"probe exited {proc.returncode}: {tail[-1] if tail else ''}"[:300],
    }


def _decline_reason(record: dict) -> str | None:
    """Extract the attributed reason from a fail-closed direct-path refusal.

    The child formats the error as "<ExceptionType>: <message>", so the
    fail-closed prefix is located rather than anchored.
    """
    message = record.get("error", "")
    start = message.find(_DECLINE_PREFIX)
    if start < 0:
        return None
    reason = message[start + len(_DECLINE_PREFIX) :]
    if _DECLINE_SUFFIX in reason:
        reason = reason.split(_DECLINE_SUFFIX, 1)[0]
    return reason.strip()


def _is_decline(record: dict) -> bool:
    """True when the child refused via the fail-closed direct path."""
    return _DECLINE_PREFIX in record.get("error", "")


def _declined_stage(reason: str | None) -> str | None:
    """The builder stage a decline is attributed to, when it names one."""
    if not reason:
        return None
    match = re.match(r"stage '([^']+)'", reason)
    return match.group(1) if match else None


def _sweep_models(model_names) -> list[dict]:
    """Probe every model, keeping the committed selection order."""
    workers = int(os.environ.get("BNG_SWEEP_WORKERS", "8"))
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for record in pool.map(_sweep_child, model_names):
            results.append(record)
    order = {name: i for i, name in enumerate(model_names)}
    results.sort(key=lambda r: order.get(r["model"], len(order)))
    return results


@pytest.mark.nf
@pytest.mark.slow
@pytest.mark.parametrize("model_name", NF_MODELS)
def test_nf_vs_native(model_name, api, work_dir):
    require_oracle(
        oracle_nfsim.nfsim_available(),
        "native NFsim binary not found (set NFSIM_BIN)",
    )

    t_end, n_steps, n_runs = 50.0, 50, 200
    native = oracle_nfsim.ensemble(
        model_name, work_dir / "native", n_runs=n_runs, t_end=t_end, n_steps=n_steps
    )
    require_oracle(bool(native), "native NFsim produced no output for this model")

    test = runner.run_api_ensemble(
        model_name,
        method="nf",
        n_runs=n_runs,
        t_end=t_end,
        n_steps=n_steps,
        expected_construction_path="direct",
    )
    diff = compare.compare_stochastic(
        native,
        test,
        min_ref_runs=n_runs,
        min_test_runs=n_runs,
    )
    assert diff.ok, f"NF vs native mismatch [{model_name}]: {diff.summary()}"


def test_nf_fixed_seed_direct_matches_native_at_final_endpoint(api, work_dir):
    """Pin one seed and compare direct BNG3 construction with native NFsim."""
    model_name = "simple_system"
    t_end, n_steps, seed = 50.0, 50, 7
    xml_path = oracle_nfsim.write_model_xml(
        model_name, work_dir / "native" / f"{model_name}.xml"
    )
    require_oracle(xml_path is not None, "BNG3 did not emit native-oracle BNG-XML")
    assert xml_path is not None

    native_path, native_error = oracle_nfsim.run_nfsim(
        xml_path,
        work_dir / "native",
        t_end=t_end,
        n_steps=n_steps,
        seed=seed,
    )
    require_oracle(
        native_path is not None,
        f"native NFsim produced no fixed-seed output: {native_error}",
    )
    assert native_path is not None
    native_data, native_columns = compare.parse_gdat(native_path)
    require_oracle(
        native_data is not None and native_columns is not None,
        "native NFsim fixed-seed output could not be parsed",
    )
    assert native_data is not None and native_columns is not None

    direct = runner.run_api(
        model_name,
        method="nf",
        seed=seed,
        t_end=t_end,
        n_steps=n_steps,
    )
    assert direct.construction_path == "direct"
    diff = compare.compare_trajectories(
        native_data,
        native_columns,
        direct.data,
        direct.columns,
        rtol=0.0,
        atol=0.0,
    )
    assert (
        diff.ok or diff.max_rel_err == 0.0
    ), f"fixed-seed direct/native NFsim mismatch: {diff.summary()}"


@pytest.mark.nf
@pytest.mark.parametrize("model_name", NF_MODELS)
def test_nf_ast_direct_matches_xml(model_name, api, work_dir, monkeypatch):
    """ast-direct construction must match the in-memory-XML construction."""
    t_end, n_steps, seed = 50.0, 50, 7

    monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
    monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
    xml_traj = runner.run_api(
        model_name, method="nf", seed=seed, t_end=t_end, n_steps=n_steps
    )

    monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)
    # The direct leg must not be allowed to fall back to XML.  Otherwise this
    # shadow test can degenerate into XML-vs-XML and report a false green when
    # direct construction regresses.
    monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)
    direct_traj = runner.run_api(
        model_name, method="nf", seed=seed, t_end=t_end, n_steps=n_steps
    )

    assert xml_traj.construction_path == "in-memory-xml"
    assert direct_traj.construction_path == "direct"

    # Same seed + same engine RNG => identical trajectories if construction matches.
    diff = compare.compare_trajectories(
        xml_traj.data,
        xml_traj.columns,
        direct_traj.data,
        direct_traj.columns,
        rtol=0.0,
        atol=0.0,
    )
    assert (
        diff.ok or diff.max_rel_err == 0.0
    ), f"ast-direct diverges from in-memory-XML [{model_name}]: {diff.summary()}"


# A site whose states are only ever mentioned from patterns has no declared
# order: the atomizer discovers them in the order it reads them, and BNGL block
# order is not semantic.  `species first` below makes '2' the first state
# discovered; `observables first` makes it the third.  Both models seed the
# same 100 molecules in state 2, so both must report them under O2 -- on both
# construction routes.  The direct path used to write the seed with the
# discovery-order index, which put every molecule in state 0 whenever the
# species block came first (models/ANx.bngl declares RD(...,m~2) there).
_SEED_STATE_ORDER_CASES = {
    "species_first": """\
begin parameters
  k 0.1
end parameters
begin species
  A(s~2) 100
end species
begin observables
  Molecules O0 A(s~0)
  Molecules O1 A(s~1)
  Molecules O2 A(s~2)
  Molecules O3 A(s~3)
  Molecules Otot A()
end observables
begin reaction rules
  A(s) -> A(s) k
end reaction rules
""",
    "observables_first": """\
begin parameters
  k 0.1
end parameters
begin observables
  Molecules O0 A(s~0)
  Molecules O1 A(s~1)
  Molecules O2 A(s~2)
  Molecules O3 A(s~3)
  Molecules Otot A()
end observables
begin species
  A(s~2) 100
end species
begin reaction rules
  A(s) -> A(s) k
end reaction rules
""",
}


def _result_to_trajectory(result) -> tuple:
    """(data, columns) for a simulate() result: time first, then observables."""
    import numpy as np

    names = list(result.observables)
    data = np.column_stack(
        [np.asarray(result.time, dtype=float)]
        + [np.asarray(result.observables[name], dtype=float) for name in names]
    )
    return data, ["time", *names]


@pytest.mark.nf
@pytest.mark.parametrize("block_order", sorted(_SEED_STATE_ORDER_CASES))
def test_nf_seed_site_state_is_resolved_by_name(block_order, api, work_dir,
                                                monkeypatch):
    """A seed's site state must be bound by name, not by discovery order.

    Both construction routes must also agree with each other at rtol=atol=0:
    a seed is a declaration, and the direct path is not free to interpret it
    differently from the compatibility path.
    """
    source = work_dir / f"seed_state_{block_order}.bngl"
    source.write_text(_SEED_STATE_ORDER_CASES[block_order], encoding="utf-8")

    monkeypatch.setenv("BNG_NFSIM_FORCE_XML", "1")
    monkeypatch.setenv("BNG_NFSIM_ALLOW_XML_FALLBACK", "1")
    xml_result = api.load(str(source)).simulate(
        method="nf", seed=7, t_end=0.1, n_steps=10
    )
    assert xml_result.construction_path == "in-memory-xml"

    monkeypatch.delenv("BNG_NFSIM_FORCE_XML", raising=False)
    monkeypatch.delenv("BNG_NFSIM_ALLOW_XML_FALLBACK", raising=False)
    direct_result = api.load(str(source)).simulate(
        method="nf", seed=7, t_end=0.1, n_steps=10
    )
    assert direct_result.construction_path == "direct", (
        "the direct path declined a model the XML path accepts; a decline is "
        f"a reportable measurement, not a pass: "
        f"{direct_result.direct_unavailable_reason!r}"
    )

    # The seeded pool is in state 2, so it is reported under O2 and nowhere
    # else. Asserting the name as well as the count is the point: the count
    # alone would also pass if every observable had collapsed onto one pool.
    for leg, result in (("direct", direct_result), ("xml", xml_result)):
        final = {name: float(values[-1]) for name, values in result.observables.items()}
        assert final["O2"] == 100.0, f"[{block_order}/{leg}] seed pool not under O2: {final}"
        assert final["Otot"] == 100.0, f"[{block_order}/{leg}] Otot: {final}"
        for name in ("O0", "O1", "O3"):
            assert final[name] == 0.0, f"[{block_order}/{leg}] {name}: {final}"

    xml_data, xml_columns = _result_to_trajectory(xml_result)
    direct_data, direct_columns = _result_to_trajectory(direct_result)
    diff = compare.compare_trajectories(
        xml_data, xml_columns, direct_data, direct_columns, rtol=0.0, atol=0.0
    )
    assert (
        diff.ok or diff.max_rel_err == 0.0
    ), f"ast-direct diverges from in-memory-XML [{block_order}]: {diff.summary()}"


@pytest.mark.nf
@pytest.mark.slow
def test_tierp_direct_path_outcome_is_measured_and_attributed(api):
    """Measure what the direct NFsim path does with every committed tier-P model.

    ADR 0001 holds direct lowering "gated against the compatibility/XML path
    until the full parity matrix is green". This is that matrix, measured. The
    bar is not "every model is direct" -- most of them legitimately are not --
    it is that every model lands in a bucket, every decline names its cause,
    and every model the direct path accepts still matches in-memory-XML
    bit-for-bit under one fixed seed at rtol=atol=0.

    The per-model result is written to build/validation/direct_path_sweep.json
    so the counts can be read off a run without re-executing it.
    """
    if not TIER_P_MODELS:
        pytest.skip("committed tier-P selection is empty")

    records = _sweep_models(TIER_P_MODELS)

    # Every probed model must be accounted for, in the order it was selected.
    assert [r["model"] for r in records] == TIER_P_MODELS

    # Classified by identity, and the buckets are mutually exclusive by
    # construction: a model is exactly one of accepted / declined / incomplete
    # / unattributed. Value-based membership would silently collapse two
    # models that happened to produce identical records.
    incomplete = [r for r in records if r.get("status") == "incomplete"]
    accepted = [r for r in records if r.get("direct_status") == "accepted"]
    declined = [r for r in records if r.get("direct_status") is None and _is_decline(r)]
    # Models that fail to parse never reach the nine-stage builder, so the
    # direct path is not what turned them down. Reporting them as declines
    # would blame the migration for a pre-existing syntax problem.
    not_loadable = [
        r
        for r in records
        if r.get("direct_status") is None
        and not _is_decline(r)
        and r.get("status") != "incomplete"
    ]
    classified = {id(r) for r in incomplete + accepted + declined + not_loadable}
    unattributed = [r for r in records if id(r) not in classified]
    compared = [r for r in accepted if r.get("parity_status") == "compared"]
    parity_unavailable = [r for r in accepted if r.get("parity_status") != "compared"]

    for record in not_loadable:
        print(f"NOT-LOADABLE [{record['model']}]: {record.get('error')}")

    # Everything below the report write is an assertion about the numbers; the
    # numbers themselves are written first, unconditionally.
    #
    # A sweep that classified nothing has measured nothing. Guard against the
    # probe silently breaking: tier-NF is the set the direct path is
    # independently pinned to accept, so it must come back accepted here too.
    #
    # Divergences are collected rather than raised one at a time; the sweep's
    # job is to report the full picture, and an early assert would hide every
    # model after it. The tolerance is not relaxed -- rtol/atol stay 0.0 -- and
    # a divergence is still a hard failure once the report is written.
    diverged = []
    incomparable = []
    for record in compared:
        if record["xml_construction_path"] != "in-memory-xml":
            raise AssertionError(
                f"XML leg ran {record['xml_construction_path']!r} "
                f"[{record['model']}]"
            )
        shared = set(record["direct_columns"]) & set(record["xml_columns"])
        if not shared:
            # Neither leg exposes a common observable, so there is no
            # trajectory to compare. The comparator reports this as
            # max_rel_err=inf with no offending column; counting that as a
            # divergence would report a harness limitation as an engine bug.
            incomparable.append(record)
            print(
                f"NO-COMPARABLE-OBSERVABLES [{record['model']}]: "
                f"direct={record['direct_columns']} xml={record['xml_columns']}"
            )
        elif record["max_rel_err"] != 0.0:
            diverged.append(record)
            print(
                f"DIVERGED [{record['model']}]: max_rel_err="
                f"{record['max_rel_err']} on {record['max_rel_col']!r}"
            )
    diverged_ids = {id(r) for r in diverged}
    incomparable_ids = {id(r) for r in incomparable}

    for record in incomplete:
        print(f"INCOMPLETE [{record['model']}]: {record.get('error')}")
    for record in parity_unavailable:
        print(f"PARITY-UNAVAILABLE [{record['model']}]: {record.get('parity_error')}")
    for record in accepted:
        if record["construction_path"] != "direct":
            raise AssertionError(
                f"direct-path probe reported accepted but ran "
                f"{record['construction_path']!r} [{record['model']}]"
            )
        if record["direct_unavailable_reason"]:
            raise AssertionError(
                f"accepted run reported a decline reason "
                f"[{record['model']}]: {record['direct_unavailable_reason']!r}"
            )
    for record in declined:
        if not _decline_reason(record) or _DECLINE_SUFFIX not in record["error"]:
            raise AssertionError(
                f"decline did not come from the fail-closed direct path, or "
                f"carried no attributed reason [{record['model']}]: "
                f"{record['error']}"
            )

    def outcome(record: dict) -> str:
        """The single bucket a model landed in, written verbatim to the report."""
        if id(record) in diverged_ids:
            return "diverged"
        if id(record) in incomparable_ids:
            return "accepted_no_comparable_observables"
        if record.get("direct_status") == "accepted":
            return "accepted"
        if id(record) in {id(r) for r in declined}:
            return "declined"
        if id(record) in {id(r) for r in not_loadable}:
            return "not_loadable"
        if id(record) in {id(r) for r in incomplete}:
            return "incomplete"
        return "unclassified"

    report = {
        "tier": "p",
        "models_attempted": len(records),
        "accepted": len(accepted),
        "accepted_and_compared": len(compared),
        "accepted_parity_unavailable": len(parity_unavailable),
        "declined": len(declined),
        "diverged": len(diverged),
        "accepted_no_comparable_observables": len(incomparable),
        "not_loadable": len(not_loadable),
        "incomplete": len(incomplete),
        "unclassified": len(unattributed),
        "seed": SWEEP_SEED,
        "t_end": SWEEP_T_END,
        "n_steps": SWEEP_N_STEPS,
        "records": [
            {
                "model": r["model"],
                "outcome": outcome(r),
                "construction_path": r.get("construction_path"),
                "direct_unavailable_reason": _decline_reason(r)
                or r.get("direct_unavailable_reason"),
                "stage": _declined_stage(_decline_reason(r)),
                "parity_status": r.get("parity_status"),
                "max_rel_err": r.get("max_rel_err"),
                "max_rel_col": r.get("max_rel_col"),
                "diverged": id(r) in diverged_ids,
                "no_comparable_observables": id(r) in incomparable_ids,
                "parity_note": r.get("parity_note"),
                "direct_columns": r.get("direct_columns"),
                "xml_columns": r.get("xml_columns"),
                "error": r.get("error"),
                "parity_error": r.get("parity_error"),
            }
            for r in records
        ],
        "diverged_models": sorted(r["model"] for r in diverged),
    }
    SWEEP_ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    SWEEP_ARTIFACT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        f"tier-P direct path: {report['accepted']} accepted, "
        f"{report['declined']} declined, {report['diverged']} diverged, "
        f"{report['accepted_no_comparable_observables']} without comparable "
        f"observables, {report['not_loadable']} not loadable, "
        f"{report['incomplete']} incomplete "
        f"of {report['models_attempted']} attempted -> {SWEEP_ARTIFACT}"
    )
    # The buckets are a partition of the attempt list. Checking the sum keeps a
    # mis-keyed count from silently under-reporting a whole category.
    accounted = (
        len(accepted)
        + len(declined)
        + len(not_loadable)
        + len(incomplete)
        + len(unattributed)
    )
    assert accounted == len(records), (
        f"direct-path buckets sum to {accounted} for {len(records)} models: "
        f"{len(accepted)} accepted + {len(declined)} declined + "
        f"{len(not_loadable)} not loadable + {len(incomplete)} incomplete + "
        f"{len(unattributed)} unclassified"
    )
    assert len(compared) + len(parity_unavailable) == len(
        accepted
    ), "accepted models must each be compared or explicitly unavailable"
    assert accepted, (
        "direct-path sweep accepted nothing; the probe is broken "
        f"({len(incomplete)} incomplete, first: "
        f"{incomplete[0].get('error') if incomplete else 'n/a'})"
    )
    accepted_names = {r["model"] for r in accepted}
    assert (
        set(NF_MODELS) <= accepted_names
    ), "tier-NF models not accepted by the sweep: " + ", ".join(
        sorted(set(NF_MODELS) - accepted_names)
    )

    # Asserted last, after the artifact is on disk, so a divergence or an
    # unclassified outcome costs the numbers rather than replacing them.
    # A model that neither ran nor refused is a harness or engine problem, not
    # a measurement, and is never folded into "declined".
    assert not unattributed, "unclassified direct-path outcomes: " + ", ".join(
        f"{r['model']} ({r.get('error', r.get('status'))})" for r in unattributed
    )

    # ADR 0001 gates direct lowering on the parity matrix being green.  The
    # remaining divergences are the AN family's seed-state-order defect
    # (_KNOWN_SEED_STATE_ORDER_DIVERGENCES), so the sweep xfails rather than
    # absorbing them into a pass.  The marker is strict in both directions and
    # the report above is already on disk by the time either check runs.
    diverged_names = {r["model"] for r in diverged}
    by_name = {r["model"]: r for r in diverged}
    unexpected = sorted(diverged_names - set(_KNOWN_SEED_STATE_ORDER_DIVERGENCES))
    assert not unexpected, (
        f"{len(unexpected)} untracked tier-P model(s) accepted by the direct "
        f"path diverge from in-memory-XML at rtol=atol=0: "
        + ", ".join(
            f"{name} (max_rel_err={by_name[name]['max_rel_err']} on "
            f"{by_name[name]['max_rel_col']!r})"
            for name in unexpected
        )
    )
    stale = sorted(set(_KNOWN_SEED_STATE_ORDER_DIVERGENCES) - diverged_names)
    assert not stale, (
        "the seed-state-order xfail is stale: "
        + ", ".join(stale)
        + " no longer diverge, so the marker is hiding a passing model. "
        "Remove the name from _KNOWN_SEED_STATE_ORDER_DIVERGENCES."
    )
    if diverged:
        pytest.xfail(
            "known seed-state-order divergence in the direct path: "
            + ", ".join(sorted(diverged_names))
            + " (cpp/nfsim/NFinput/NFinput_fromCompiled.cpp, seed-species stage)"
        )
