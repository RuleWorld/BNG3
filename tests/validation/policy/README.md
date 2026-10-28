# Anti-gaming CI policy

The stable public check IDs are declared in `antigaming.py`. PR workflow checks
load both checker files with `git show BASE:path`, validate the base revision,
then inspect the proposed tree. Missing or partial checker files fail closed.
The one-time bootstrap is allowed only when the base revision lacks both
checker files and the diff from that base contains exactly this policy
package. This also covers the push-to-main run after the initial policy merge.
Its log label is `BOOTSTRAP SETUP (not base-revision PASS)`.

`run_pr_checks(root, base)` returns errors keyed by stable check ID. The
individual pure checks accept a Git checkout path and base commit, so mutation
acceptance fixtures can construct disposable repositories and verify
rejection cases. `run_antigaming.py` is the CI command-line entry point.

Product changes remain separate from edits to protected acceptance criteria,
except for a reviewed SBML verdict improvement that advances existing case
stages to `passed`. Such a change must pair the expectation manifest with an
append-only `provenance/sbml-campaign/expectation-improvements.json` record.
The base-revision policy verifies that the suite identity and case membership
are unchanged, only non-pass stage verdicts advance to `passed`, the evidence
matches those exact transitions, and product code is unchanged after the
measured commit. The manifest provenance note must identify the measured
commit, report digest, workflow run, job, and artifact.

Reviewers must inspect the referenced hosted report artifact, confirm that it
supports every recorded transition, and verify its SHA-256 digest before
approving the PR. The policy validates the evidence record and its relationship
to the manifest; it does not fetch GitHub artifacts or establish that their
contents are scientifically valid.

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
