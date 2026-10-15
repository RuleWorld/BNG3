"""Discovery must expose new code without claiming it has semantic coverage."""

from tests.validation import inventory


def test_new_public_symbol_is_unverified_even_when_module_has_tests(tmp_path):
    source = tmp_path / "python/bionetgen/model.py"
    source.parent.mkdir(parents=True)
    source.write_text("class Model:\n    def simulate(self): pass\n")
    rows = inventory.discover_capabilities(tmp_path, [])
    row = next(r for r in rows if r["symbol"] == "Model.simulate")
    assert row["support"] == "unverified"
    assert row["coverage"] == "NOT_TESTED"
    assert row["missing_tests"]
    assert row["implementation"]["line"] == 2


def test_discovery_retains_unknown_cpp_and_extracts_actions_and_features(tmp_path):
    paths = {
        "cpp/new_backend/Novel.cpp": "// new implementation\n",
        "cpp/actions/ActionDispatch.cpp": 'if (actionName == "newaction") {}\n',
        "cpp/compile/Capabilities.hpp": "enum class Feature { Units, NewFeature, Count, };",
    }
    for name, content in paths.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    rows = inventory.discover_capabilities(tmp_path, [])
    assert any(r["implementation"]["path"] == "cpp/new_backend/Novel.cpp" for r in rows)
    assert {"action.newaction", "feature.NewFeature"} <= {r["id"] for r in rows}
    assert len({r["id"] for r in rows}) == len(rows)


def test_corpus_keeps_duplicate_stems_and_never_calls_hints_support(tmp_path):
    for directory in ("models/a", "models/b"):
        p = tmp_path / directory / "same.bngl"
        p.parent.mkdir(parents=True)
        p.write_text("begin model\nend model\nsimulate_nf({t_end=>100000})\n")
    rows = inventory.discover_models(tmp_path)
    assert len(rows) == 2
    assert all(r["execution_policy"] == "stage-only" for r in rows)
    assert all("network-free" in r["capability_hints"] for r in rows)
    assert all(r["classification_confidence"] == "lexical-hint" for r in rows)


def test_mapping_rejects_missing_implementation_and_test_paths(tmp_path):
    errors = inventory.validate_plan(
        tmp_path,
        {
            "capabilities": [
                {
                    "id": "bad",
                    "sources": ["cpp/missing.cpp"],
                    "tests": ["tests/missing.py"],
                    "support": "implemented",
                }
            ],
            "suites": [],
        },
    )
    assert any("cpp/missing.cpp" in e for e in errors)
    assert any("tests/missing.py" in e for e in errors)


def test_conditional_exports_accessors_and_gpu_sources_are_discovered(tmp_path):
    p = tmp_path / "python/bionetgen/__init__.py"
    p.parent.mkdir(parents=True)
    p.write_text(
        "try:\n    def run(): pass\nexcept ImportError:\n    def run(): pass\nclass Model:\n    @property\n    def value(self): pass\n    @value.setter\n    def value(self, x): pass\n"
    )
    for ext in ("cu", "mm", "hh"):
        p = tmp_path / f"cpp/gpu/backend.{ext}"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("// implementation")
    rows = inventory.discover_capabilities(tmp_path, [])
    assert any(r["symbol"] == "run" for r in rows)
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(
        any(r["implementation"]["path"].endswith("." + ext) for r in rows)
        for ext in ("cu", "mm", "hh")
    )


def test_bindings_and_lean_declarations_are_unverified_discovery_units(tmp_path):
    for name, text in {
        "cpp/bindings/model.cpp": '.def("simulate", &Model::simulate)',
        "formal/lean/BNG/Contract.lean": "theorem balance : True := by trivial\n",
    }.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    rows = inventory.discover_capabilities(tmp_path, [])
    assert {"binding", "lean-declaration"} <= {r["kind"] for r in rows}
    assert all(r["support"] == "unverified" for r in rows)


def test_semantic_claim_keeps_its_own_issues_when_source_file_is_shared(tmp_path):
    p = tmp_path / "cpp/engine/Shared.cpp"
    p.parent.mkdir(parents=True)
    p.write_text("// two independent capabilities")
    claims = [
        {
            "id": name,
            "sources": ["cpp/engine/Shared.cpp"],
            "tests": [],
            "issues": [issue],
            "support": "partial",
        }
        for name, issue in [("one", 1), ("two", 2)]
    ]
    rows = inventory.discover_capabilities(tmp_path, claims)
    one = next(r for r in rows if r["id"] == "one")
    assert one["issues"] == [1]
