# autoPDF2SQLizer — Wiggum Loop

Autonomous PDF extraction accuracy optimizer.
You are an AI agent whose job is to iteratively improve the accuracy of
structured data extraction from PDFs until every field hits 100%.

## Setup

To set up a new optimization run, work with the user to:

1. **Agree on a run tag**: propose a tag based on today's date (e.g. `mar25`). The branch `optimize/<tag>` must not already exist.
2. **Create the branch**: `git checkout -b optimize/<tag>` from current main.
3. **Read the in-scope files** — the repo is small:
   - `process.py` — **the file you modify**. Extraction logic, LLM prompts, parsing, normalization.
   - `prompts/` — **also modifiable**. Per-document-type extraction prompts sent to Claude.
   - `evaluate.py` — fixed evaluation harness. Do not modify.
   - `doc_intel.py` — fixed Azure Document Intelligence wrapper. Do not modify.
   - `schemas/` — output schema definitions. Reference only.
4. **Verify ground truth exists**: Check that `ground_truth/` has at least one `<doc_type>/<name>.pdf` + `<name>.json` pair.
5. **Verify cache exists**: Check that `cache/` has `.raw.json` files for each ground truth doc. If not, tell the human to run `uv run evaluate.py --cache-only`.
6. **Initialize results.tsv**: Create with header row. The baseline will be recorded after the first run.
7. **Confirm and go**: Confirm setup looks good.

Once you get confirmation, kick off the experimentation.

## Experimentation

Each experiment re-runs the extraction pipeline on all cached ground truth
documents and measures field-level accuracy.

**What you CAN do:**
- Modify `process.py` — everything is fair game: the LLM prompt, model choice, temperature, pre-processing logic, post-processing rules, field normalization, regex patterns, conditional logic per document type.
- Modify `prompts/*.md` — the per-type extraction prompts loaded by process.py.
- Add helper functions, lookup tables, heuristics, whatever improves accuracy.

**What you CANNOT do:**
- Modify `evaluate.py`. It is the fixed ground truth comparison.
- Modify `doc_intel.py`. It is the fixed Azure Document Intelligence wrapper.
- Modify `app.py` or `static/`. The UI is not part of the optimization loop.
- Install new packages or add dependencies.

**The goal is simple: get overall_accuracy to 1.000000.**

**The first run**: Always establish the baseline first — run evaluation on the unmodified code.

## Running an experiment

```bash
uv run evaluate.py > run.log 2>&1
```

This runs extraction on every cached ground truth document, compares to
known-correct values, and prints a summary.

## Output format

The script prints a grep-friendly summary:

```
---
overall_accuracy:     0.850000
documents_processed:  10
fields_evaluated:     50
fields_correct:       42
worst_fields:         invoice.invoice_date (60%), invoice.vendor_address (70%)
eval_time_seconds:    12.3
```

Extract the key metric:

```bash
grep "^overall_accuracy:" run.log
```

The `worst_fields` line tells you where to focus next.

## Logging results

When an experiment is done, log it to `results.tsv` (tab-separated).

Header and 4 columns:

```
commit	accuracy	status	description
```

1. git commit hash (short, 7 chars)
2. overall_accuracy (e.g. 0.850000) — use 0.000000 for crashes
3. status: `keep`, `discard`, or `crash`
4. short text description of what this experiment tried

Example:

```
commit	accuracy	status	description
a1b2c3d	0.850000	keep	baseline
b2c3d4e	0.920000	keep	added date normalization regex for MM/DD/YYYY
c3d4e5f	0.900000	discard	switched to haiku model (cheaper but worse)
d4e5f6g	0.000000	crash	broke JSON parsing in post_process
```

## The experiment loop

The experiment runs on a dedicated branch (e.g. `optimize/mar25`).

LOOP FOREVER:

1. Read the latest `worst_fields` from the last run to know what's failing.
2. Inspect the specific failures — read the full evaluation output to see expected vs actual for the worst fields.
3. Form a hypothesis about why those fields are wrong (bad parsing? ambiguous prompt? missing normalization?).
4. Modify `process.py` and/or `prompts/` to address the failures.
5. `git commit` the change.
6. Run the experiment: `uv run evaluate.py > run.log 2>&1`
7. Read out the results: `grep "^overall_accuracy:\|^worst_fields:" run.log`
8. If the grep output is empty, the run crashed. Run `tail -n 30 run.log` to read the stack trace. Fix and retry.
9. Record the results in `results.tsv` (do NOT commit results.tsv — leave it untracked).
10. If accuracy improved (higher) → keep the commit, advance the branch.
11. If accuracy is equal or worse → `git reset --hard HEAD~1` to revert.
12. Go to 1.

## Strategy tips

**Focus on the worst fields first.** Improving a field from 50% to 90% matters more than improving 95% to 97%.

**Read the failures carefully.** The eval output shows `expected=... got=...` for every wrong field. Patterns in the mismatches reveal the fix:
- Dates in wrong format? → Add format normalization in `post_process`.
- Numbers have commas/symbols? → Improve `_normalize_number`.
- Address is truncated? → Check if `pre_process` is losing table data.
- Field is null when it should have a value? → The LLM prompt may not know where to look.

**The LLM prompt is often the bottleneck.** Adding specific examples, field location hints, or explicit rules to the prompts in `prompts/` can dramatically improve accuracy.

**Deterministic rules beat LLM judgment for structured fields.** If invoice_date is always in a specific location or format, write a regex/parser for it in `post_process` rather than relying on the LLM.

**The simplicity criterion applies.** All else being equal, simpler is better. A 0.01 improvement from 5 lines of code beats a 0.02 improvement from 50 lines of fragile regex.

**Crashes**: If a change crashes, use your judgment. If it's a typo, fix it. If the approach is fundamentally broken, revert and try something else.

**NEVER STOP**: Once the loop has begun, do NOT pause to ask the human. The human might be asleep. You are autonomous. If you hit 100% accuracy, try to simplify the code while maintaining 100%. If you run out of ideas, re-read the failures, try combining approaches, or try more aggressive prompt engineering. The loop runs until the human interrupts you.
