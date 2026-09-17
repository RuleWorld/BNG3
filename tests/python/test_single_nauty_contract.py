"""Contract: exactly one bundled nauty build.

WO-1b unified canonical graph labeling onto a single nauty library. Before it,
``cpp/nauty/*.c`` was compiled into the ``nauty`` target *and*
``cpp/nfsim/nauty24/*.c`` was globbed separately into ``nfsim_core``, so two
builds of the same upstream C library were linked into every binary. nauty
keeps mutable state at file scope (static workspace buffers and ``DYNALLSTAT``
allocations), so a duplicate build means duplicate global state and duplicate
symbols that the linker resolves silently.

This is a source/build-structure contract, so it runs without compiling
anything. It is deliberately a *test* rather than a comment in CMakeLists,
because the failure mode is someone re-adding a vendored copy for a subsystem
that needs slightly different behavior — which is exactly when a comment gets
skipped. See ``cpp/nauty/README.md``.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
CPP = ROOT / "cpp"

# The pristine upstream distribution is kept for provenance but is not
# compiled: the `nauty` target globs `nauty/*.c` non-recursively.
UPSTREAM_PROVENANCE_DIR = CPP / "nauty" / "nauty24"


def _compiled_nauty_dirs():
    """Directories holding nauty translation units that a target could glob."""
    found = set()
    for source in CPP.rglob("nauty.c"):
        found.add(source.parent)
    for source in CPP.rglob("nautil.c"):
        found.add(source.parent)
    return found


def test_only_one_nauty_tree_is_compiled():
    dirs = _compiled_nauty_dirs()
    # cpp/nauty (compiled) plus cpp/nauty/nauty24 (provenance only).
    unexpected = dirs - {CPP / "nauty", UPSTREAM_PROVENANCE_DIR}
    assert not unexpected, (
        "a second nauty source tree reappeared: "
        + ", ".join(str(d.relative_to(ROOT)) for d in sorted(unexpected))
        + ". Add a wrapper in cpp/core instead of vendoring another copy; "
        "see cpp/nauty/README.md."
    )


def test_nfsim_does_not_carry_its_own_nauty():
    assert not (CPP / "nfsim" / "nauty24").exists(), (
        "cpp/nfsim/nauty24/ is back. nfsim_core links the shared `nauty` "
        "target; it must not compile its own copy."
    )


def test_cmake_compiles_nauty_once_and_links_it_into_nfsim():
    cmake = (CPP / "CMakeLists.txt").read_text()

    # Exactly one add_library for nauty, globbing exactly one directory.
    assert cmake.count("add_library(nauty") == 1
    assert 'file(GLOB NAUTY_SOURCES "nauty/*.c")' in cmake

    # No second glob feeding nauty sources into another target.
    assert "NFSIM_NAUTY_C" not in cmake, (
        "the nfsim-local nauty glob is back in cpp/CMakeLists.txt"
    )
    assert "nauty24/*.c" not in cmake

    # nfsim_core must consume the shared target rather than a private path.
    assert "target_link_libraries(nfsim_core PUBLIC" in cmake
    link_line = next(
        line
        for line in cmake.splitlines()
        if line.startswith("target_link_libraries(nfsim_core PUBLIC")
    )
    assert "nauty" in link_line, (
        "nfsim_core no longer links the shared nauty target: " + link_line
    )
    assert "$<TARGET_PROPERTY:nauty,INTERFACE_INCLUDE_DIRECTORIES>" in cmake


def test_nfsim_includes_the_shared_nauty_header():
    complex_cpp = (CPP / "nfsim" / "NFcore" / "complex.cpp").read_text()
    assert "../nauty24/nausparse.h" not in complex_cpp, (
        "complex.cpp is including a relative nfsim-local nauty header again"
    )
    assert '#include "nausparse.h"' in complex_cpp


@pytest.mark.parametrize(
    "source", ["nauty.h", "nauty.c", "nautil.c", "nausparse.h", "nausparse.c"]
)
def test_compiled_nauty_keeps_the_nset_rename(source):
    """The compiled copy must keep the ``set`` -> ``nset`` typedef patch.

    Upstream nauty defines ``typedef setword set;`` at global scope. NFsim's
    C++ translation units use ``using namespace std;``, so the unqualified name
    collides with ``std::set``. Reverting to the unpatched upstream header
    would break the NFsim side of the shared target.
    """
    text = (CPP / "nauty" / source).read_text(errors="replace")
    assert "nset" in text, (
        f"cpp/nauty/{source} lost the nset rename; NFsim cannot include it"
    )


def test_compiled_nauty_header_guards_systypes_on_msvc():
    """MSVC has no <sys/types.h>.

    The former ``cpp/nauty`` copy declared ``HAVE_SYSTYPES_H 1``
    unconditionally while the NFsim copy guarded it. Unifying on the NFsim
    variant fixed that; keep it fixed.
    """
    text = (CPP / "nauty" / "nauty.h").read_text(errors="replace")
    assert "#define HAVE_SYSTYPES_H  0" in text
    assert "_MSC_VER" in text
