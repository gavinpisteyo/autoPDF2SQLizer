#!/bin/bash
# =============================================================================
# Wiggum Loop Runner
# =============================================================================
# Spawns fresh Claude Code agents in a loop. Each agent:
#   1. Reads the current code + evaluation results (no history)
#   2. Runs a batch of experiments (modify process.py → evaluate → keep/discard)
#   3. Exits (context is gone)
#
# The git branch is the only memory. Good changes survive as commits.
# Bad changes are reverted. Next agent sees only the current best code.
#
# Usage:
#   ./wiggum.sh                                 # run on current branch forever
#   ./wiggum.sh 10                              # run 10 agent cycles
#   ./wiggum.sh --instance oil-gas-leases       # run on a specific client branch
#   ./wiggum.sh --instance fintech-checks 20    # 20 cycles on fintech branch
#   EXPERIMENTS_PER_AGENT=3 ./wiggum.sh         # 3 experiments per agent (default: 5)
# =============================================================================

set -euo pipefail

# Parse --instance flag
INSTANCE=""
MAX_CYCLES=0
for arg in "$@"; do
    if [ "$arg" = "--instance" ]; then
        shift; INSTANCE="$1"; shift
    elif [[ "$arg" =~ ^[0-9]+$ ]]; then
        MAX_CYCLES="$arg"; shift
    fi
done

EXPERIMENTS_PER_AGENT="${EXPERIMENTS_PER_AGENT:-5}"
CYCLE=0

# Switch to client branch if specified
if [ -n "$INSTANCE" ]; then
    BRANCH="clients/${INSTANCE}"
    echo "[wiggum] Switching to instance branch: ${BRANCH}"
    git checkout "${BRANCH}" || { echo "Error: branch ${BRANCH} not found. Run: ./instance.sh create ${INSTANCE}"; exit 1; }
fi

CURRENT_BRANCH=$(git branch --show-current)

echo "========================================"
echo "  Wiggum Loop — autoPDF2SQLizer"
echo "========================================"
echo "  Branch: $CURRENT_BRANCH"
echo "  Experiments per agent: $EXPERIMENTS_PER_AGENT"
echo "  Max cycles: $([ "$MAX_CYCLES" -eq 0 ] && echo 'infinite' || echo "$MAX_CYCLES")"
echo "========================================"
echo ""

while true; do
    CYCLE=$((CYCLE + 1))

    if [ "$MAX_CYCLES" -gt 0 ] && [ "$CYCLE" -gt "$MAX_CYCLES" ]; then
        echo "[wiggum] Reached $MAX_CYCLES cycles. Stopping."
        break
    fi

    # Snapshot current accuracy before this agent runs
    BEFORE=$(grep "^overall_accuracy:" run.log 2>/dev/null | tail -1 | awk '{print $2}' || echo "unknown")

    echo ""
    echo "========================================"
    echo "  Cycle $CYCLE — spawning fresh agent"
    echo "  Current accuracy: $BEFORE"
    echo "  $(date)"
    echo "========================================"
    echo ""

    # Spawn a fresh agent with zero history.
    # It only sees: program.md, current code, current eval results.
    claude -p "You are an autonomous extraction accuracy optimizer.

Read program.md for full instructions, but here is your task:

1. Read process.py and the prompts/ directory to understand the current extraction logic.
2. Run: uv run evaluate.py > run.log 2>&1
3. Read the results: grep '^overall_accuracy:\|^worst_fields:' run.log
4. Look at the specific failures: read run.log for expected vs actual on the worst fields.
5. Modify process.py and/or prompts/ to fix the worst failures.
6. git add -A && git commit -m '<short description of what you changed>'
7. Run evaluation again: uv run evaluate.py > run.log 2>&1
8. Compare: if overall_accuracy improved, keep it. If same or worse, run: git reset --hard HEAD~1
9. Log the result to results.tsv (tab-separated: commit, accuracy, status, description).
10. Repeat steps 4-9 for $EXPERIMENTS_PER_AGENT total experiments.

Rules:
- Only modify process.py and prompts/. Nothing else.
- Do NOT ask questions. Do NOT stop. Run all $EXPERIMENTS_PER_AGENT experiments.
- If a run crashes, read the error, fix it, and retry. If unfixable, revert and move on.
- Focus on the worst_fields first — biggest accuracy gains come from fixing the worst performers." \
    --allowedTools "Edit,Write,Read,Bash,Glob,Grep" \
    2>&1 | tee "logs/cycle_${CYCLE}.log"

    # Log cycle completion
    AFTER=$(grep "^overall_accuracy:" run.log 2>/dev/null | tail -1 | awk '{print $2}' || echo "unknown")
    echo "[wiggum] Cycle $CYCLE complete. Accuracy: $BEFORE → $AFTER"
done
