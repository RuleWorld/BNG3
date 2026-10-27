# Issue 472 documentation acceptance

`docs_checks.py` evaluates `release-docs-links` and `release-docs-decisions`
against an explicit checkout. It emits a content-hash- and revision-bound JSON result and exits
nonzero if either check finds an unresolved link/reference, incomplete or
mismatched inventory mapping, conflicting active policy, or unlabeled archived
history.

```sh
python tests/validation/release/cases/issue-472/docs_checks.py \
  --docs-root /path/to/checkout \
  --report /path/to/issue-472-docs-assessment.json
```

The pytest module contains unit controls showing that each checker rejects an invalid fixture; it does not
claim that the current documentation passes. The explicit assessment is the
release acceptance result. Remote links are checked for canonical issue-link
shape; local file and Markdown-heading links are resolved in the selected tree.
