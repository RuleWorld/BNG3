import os

try:
    from cement.utils.version import get_version as cement_get_version
except ModuleNotFoundError as exc:
    if exc.name != "cement":
        raise
    cement_get_version = None

# Find VERSION file
vpath = os.path.dirname(os.path.abspath(__file__))
vpath = os.path.split(vpath)[0]
vpath = os.path.join(*[vpath, "assets", "VERSION"])
with open(vpath, "r") as f:
    v = f.read()
vtuple = [0, 0, 0, 0, 0]
for iv, ver in enumerate(v.split()):
    try:
        vtuple[iv] = int(ver)
    except:
        vtuple[iv] = ver

VERSION = tuple(vtuple)


def get_version(version=VERSION):
    if cement_get_version is not None:
        return cement_get_version(version)

    # Cement is an optional legacy extra. Without its formatter, keep the
    # defaults object importable and report the base version from this
    # module's VERSION file. The legacy Cement CLI diagnoses the missing
    # extra when a user tries to start it.
    return ".".join(str(part) for part in version[:3])
