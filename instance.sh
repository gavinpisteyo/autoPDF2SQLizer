#!/bin/bash
# =============================================================================
# Instance Manager — create and manage client branches
# =============================================================================
# Each client gets their own branch where process.py, prompts/, schemas/,
# and ground_truth/ are customized for their specific document types.
# The Wiggum loop runs per-branch, optimizing extraction for that client.
#
# Usage:
#   ./instance.sh create <name> [doc_types...]    # create a new client branch
#   ./instance.sh list                            # list all client branches
#   ./instance.sh switch <name>                   # switch to a client branch
#   ./instance.sh sync <name>                     # merge latest main into client branch
#   ./instance.sh status                          # show current branch + accuracy
#
# Examples:
#   ./instance.sh create oil-gas-leases lease_agreement
#   ./instance.sh create fintech-checks check_deposit bank_statement
#   ./instance.sh list
#   ./instance.sh sync oil-gas-leases
# =============================================================================

set -euo pipefail

BRANCH_PREFIX="clients"

cmd_create() {
    local name="$1"; shift
    local doc_types=("$@")
    local branch="${BRANCH_PREFIX}/${name}"

    if git show-ref --verify --quiet "refs/heads/${branch}" 2>/dev/null; then
        echo "Error: branch '${branch}' already exists"
        exit 1
    fi

    # Create branch from main
    echo "Creating client branch: ${branch}"
    git checkout main
    git checkout -b "${branch}"

    # Create instance config
    cat > instance.json <<EOF
{
    "name": "${name}",
    "branch": "${branch}",
    "created": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
    "doc_types": [$(printf '"%s",' "${doc_types[@]}" | sed 's/,$//')]
}
EOF

    # Set up ground truth directories for specified doc types
    for dt in "${doc_types[@]}"; do
        mkdir -p "ground_truth/${dt}"
        echo "  Created ground_truth/${dt}/"

        # Create a starter prompt if it doesn't exist
        if [ ! -f "prompts/${dt}.md" ]; then
            cat > "prompts/${dt}.md" <<PROMPT
# ${dt} Extraction

Document-type-specific extraction instructions for ${name}.
The Wiggum loop will iterate on this prompt to improve accuracy.

Pay special attention to:
- Field locations and labels specific to this document type
- Date formats commonly used
- Number formats (currency symbols, decimal separators)
- Any domain-specific terminology
PROMPT
            echo "  Created prompts/${dt}.md"
        fi
    done

    # Initialize results.tsv
    echo -e "commit\taccuracy\tstatus\tdescription" > results.tsv

    git add -A
    git commit -m "Initialize client instance: ${name}

Doc types: ${doc_types[*]}
Branch: ${branch}"

    echo ""
    echo "========================================"
    echo "  Instance '${name}' created"
    echo "  Branch: ${branch}"
    echo "  Doc types: ${doc_types[*]}"
    echo "========================================"
    echo ""
    echo "Next steps:"
    echo "  1. Upload ground truth docs:  ground_truth/<doc_type>/<name>.pdf + .json"
    echo "  2. Cache Doc Intel results:   uv run evaluate.py --cache-only"
    echo "  3. Start the Wiggum loop:     ./wiggum.sh"
    echo ""
    echo "To push this branch:"
    echo "  git push -u origin ${branch}"
}

cmd_list() {
    echo "Client instances:"
    echo ""
    local branches
    branches=$(git branch -a | grep "${BRANCH_PREFIX}/" | sed 's/^[* ]*//' | sed "s|remotes/origin/||" | sort -u)

    if [ -z "${branches}" ]; then
        echo "  (none — run './instance.sh create <name>' to get started)"
        return
    fi

    local current
    current=$(git branch --show-current)

    while IFS= read -r branch; do
        local marker="  "
        if [ "${branch}" = "${current}" ]; then
            marker="* "
        fi
        echo "${marker}${branch}"
    done <<< "${branches}"
}

cmd_switch() {
    local name="$1"
    local branch="${BRANCH_PREFIX}/${name}"

    if ! git show-ref --verify --quiet "refs/heads/${branch}" 2>/dev/null; then
        echo "Error: branch '${branch}' does not exist"
        echo "Available instances:"
        cmd_list
        exit 1
    fi

    git checkout "${branch}"
    echo "Switched to instance: ${name}"

    if [ -f instance.json ]; then
        echo "Config: $(cat instance.json)"
    fi
}

cmd_sync() {
    local name="$1"
    local branch="${BRANCH_PREFIX}/${name}"

    if ! git show-ref --verify --quiet "refs/heads/${branch}" 2>/dev/null; then
        echo "Error: branch '${branch}' does not exist"
        exit 1
    fi

    echo "Syncing '${branch}' with latest main..."
    git checkout "${branch}"
    git merge main -m "Sync with latest main" --no-edit

    echo "Done. Resolve any conflicts in process.py or prompts/ if needed."
}

cmd_status() {
    local current
    current=$(git branch --show-current)
    echo "Current branch: ${current}"

    if [ -f instance.json ]; then
        echo "Instance config:"
        cat instance.json
    fi

    if [ -f results.tsv ]; then
        local last
        last=$(tail -1 results.tsv)
        echo ""
        echo "Last result: ${last}"
    fi

    if [ -f run.log ]; then
        local acc
        acc=$(grep "^overall_accuracy:" run.log | tail -1 || echo "no eval run yet")
        echo "Current accuracy: ${acc}"
    fi
}

# --- CLI dispatch ---
case "${1:-help}" in
    create)
        shift
        if [ $# -lt 1 ]; then
            echo "Usage: ./instance.sh create <name> [doc_types...]"
            exit 1
        fi
        cmd_create "$@"
        ;;
    list)
        cmd_list
        ;;
    switch)
        shift
        cmd_switch "${1:?Usage: ./instance.sh switch <name>}"
        ;;
    sync)
        shift
        cmd_sync "${1:?Usage: ./instance.sh sync <name>}"
        ;;
    status)
        cmd_status
        ;;
    *)
        echo "Usage: ./instance.sh <command> [args]"
        echo ""
        echo "Commands:"
        echo "  create <name> [doc_types...]  Create a new client branch"
        echo "  list                          List all client branches"
        echo "  switch <name>                 Switch to a client branch"
        echo "  sync <name>                   Merge latest main into client branch"
        echo "  status                        Show current branch info"
        ;;
esac
