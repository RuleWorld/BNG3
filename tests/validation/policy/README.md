# Anti-gaming CI policy

The stable public check IDs are declared in `antigaming.py`. PR workflow checks
load both checker files with `git show BASE:path`, validate the base revision,
then inspect the proposed tree. Missing or partial checker files fail closed.
The one-time bootstrap is restricted to baseline
`3ef3ac00645dc894133a8755a1499ca86711d286`, verifies both checker files are
absent there and limits changed paths to this package. Its log label is
`BOOTSTRAP SETUP (not base-revision PASS)`.

`run_pr_checks(root, base)` returns errors keyed by stable check ID. The
individual pure checks accept a Git checkout path and base commit, so mutation
acceptance fixtures can construct disposable repositories and verify
rejection cases. `run_antigaming.py` is the CI command-line entry point.

Every Python integration run draws a fresh 31-bit seed, creates a small valid
BNGL decay source, executes it through the installed package, and uploads the
seed, case ID, source digest and revision with the source. This artifact is a
replay record for this generated case.

The scheduled mutation campaign uses a disposable shared-object Git clone and mutates the
production `BioNetGenModel.set_parameter` call by 1%. It first runs the
unchanged independent compiled-backend contract test to establish the test
environment. The mutant is killed only when that test fails; collection,
import, setup and timeout failures are infrastructure errors. A surviving
mutant or infrastructure error fails the scheduled job. The report records
the mutant classification, denominator and caught count. The initial curated
set requires 100% detection; adding curated non-equivalent mutants increases
the denominator and cannot lower that requirement. The initial baseline record
is explicitly unavailable until an exact-main scheduled artifact is reviewed.
Release qualification fails while it remains unavailable; no score is inferred
from the local or PR-branch run.
