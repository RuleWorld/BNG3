"""Execute native BNGL actions in a process bound to the caller's runtime."""

from pathlib import Path
import sys


def main():
    source, package_file, native_file, verbose = sys.argv[1:]
    package_file = Path(package_file).resolve()
    native_file = Path(native_file).resolve()
    sys.path[:0] = [str(package_file.parent.parent), str(native_file.parent)]

    import bionetgen
    from bionetgen.model import _cpp

    if Path(bionetgen.__file__).resolve() != package_file:
        raise RuntimeError("native CLI worker imported a different Python package")
    if _cpp is None or Path(_cpp.__file__).resolve() != native_file:
        raise RuntimeError("native CLI worker imported a different native extension")
    model = _cpp.parse_file(source)
    _cpp.execute(model, source, verbose=verbose == "1")


if __name__ == "__main__":
    main()
