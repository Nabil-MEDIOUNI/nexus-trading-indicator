#!/bin/bash
# Pine Script v6 Static Validator
# Catches common errors BEFORE pasting into TradingView
# Usage: bash scripts/validate-pine.sh src/nexus-indicator.pine

FILE="${1:-src/nexus-indicator.pine}"
ERRORS=0
WARNINGS=0

echo "=== Pine Script Validator ==="
echo "File: $FILE"
echo ""

if [ ! -f "$FILE" ]; then
    echo "ERROR: File not found: $FILE"
    exit 1
fi

LINES=$(wc -l < "$FILE")
echo "Lines: $LINES"

# --- ERRORS (will break on TradingView) ---

# Check //@version=6 exists
if ! grep -q '//@version=6' "$FILE"; then
    echo "ERROR: Missing //@version=6 declaration"
    ((ERRORS++))
fi

# Check indicator() or strategy() declaration
if ! grep -q 'indicator(' "$FILE" && ! grep -q 'strategy(' "$FILE"; then
    echo "ERROR: Missing indicator() or strategy() declaration"
    ((ERRORS++))
fi

# Check for var inside if blocks (common Pine v6 error)
# Pattern: line starts with spaces, then "var " inside an if block
if grep -n '^\s\+if ' "$FILE" | head -1 > /dev/null; then
    # Check for var declarations that are indented more than the surrounding if
    VAR_IN_IF=$(grep -n '^\s\{8,\}var ' "$FILE" | head -5)
    if [ -n "$VAR_IN_IF" ]; then
        echo "WARNING: Possible 'var' inside if block (check these lines):"
        echo "$VAR_IN_IF"
        ((WARNINGS++))
    fi
fi

# Check for plot() inside local scopes (if blocks, functions)
PLOT_IN_SCOPE=$(grep -n '^\s\{4,\}plot(' "$FILE" | head -5)
if [ -n "$PLOT_IN_SCOPE" ]; then
    echo "ERROR: plot() inside local scope (will fail):"
    echo "$PLOT_IN_SCOPE"
    ((ERRORS++))
fi

PLOTSHAPE_IN_SCOPE=$(grep -n '^\s\{4,\}plotshape(' "$FILE" | head -5)
if [ -n "$PLOTSHAPE_IN_SCOPE" ]; then
    echo "ERROR: plotshape() inside local scope (will fail):"
    echo "$PLOTSHAPE_IN_SCOPE"
    ((ERRORS++))
fi

# Check for self-referencing declarations (X = X)
SELF_REF=$(grep -n '^\([A-Za-z_]*\) = \1$' "$FILE" | head -5)
if [ -n "$SELF_REF" ]; then
    echo "ERROR: Self-referencing declaration (variable assigned to itself):"
    echo "$SELF_REF"
    ((ERRORS++))
fi

# Check for em dash character (project rule: use regular hyphen)
if grep -Pn '\xe2\x80\x94' "$FILE" > /dev/null 2>&1; then
    echo "ERROR: Em dash character found (use regular hyphen):"
    grep -Pn '\xe2\x80\x94' "$FILE" | head -5
    ((ERRORS++))
fi

# Check str.format with unescaped braces (common JSON error)
BAD_FORMAT=$(grep -n 'str\.format.*{"' "$FILE" | head -5)
if [ -n "$BAD_FORMAT" ]; then
    echo "ERROR: str.format() with unescaped braces (use string concat for JSON):"
    echo "$BAD_FORMAT"
    ((ERRORS++))
fi

# --- WARNINGS (won't break but indicate issues) ---

# Count inputs
INPUTS=$(grep -c 'input\.' "$FILE")
echo ""
echo "--- Stats ---"
echo "Inputs: $INPUTS"

# Count alertconditions
ALERTS=$(grep -c 'alertcondition(' "$FILE")
echo "Alert conditions: $ALERTS"

# Count alert() calls
JSON_ALERTS=$(grep -c 'alert(' "$FILE" | head -1)
echo "Alert() calls: $JSON_ALERTS"

# Count request.security calls
SECURITY=$(grep -c 'request\.security' "$FILE")
echo "request.security() calls: $SECURITY"
if [ "$SECURITY" -gt 40 ]; then
    echo "ERROR: Too many request.security() calls ($SECURITY > 40 limit)"
    ((ERRORS++))
fi

# Count tables
TABLES=$(grep -c 'table\.new' "$FILE")
echo "Tables: $TABLES"

# Count UDTs
UDTS=$(grep -c '^type ' "$FILE")
echo "User-Defined Types: $UDTS"

# Check for hardcoded colors that should use constants
HARD_BULL=$(grep -n '#22ab94' "$FILE" | grep -v 'COLOR_BULL' | grep -v 'input\.' | head -5)
if [ -n "$HARD_BULL" ]; then
    echo ""
    echo "WARNING: Hardcoded #22ab94 found (use COLOR_BULL constant):"
    echo "$HARD_BULL"
    ((WARNINGS++))
fi

HARD_BEAR=$(grep -n '#f7525f' "$FILE" | grep -v 'COLOR_BEAR' | grep -v 'input\.' | head -5)
if [ -n "$HARD_BEAR" ]; then
    echo "WARNING: Hardcoded #f7525f found (use COLOR_BEAR constant):"
    echo "$HARD_BEAR"
    ((WARNINGS++))
fi

# Check for color.new(color.white, 100) that should use COLOR_TRANSPARENT
HARD_TRANS=$(grep -n 'color\.new(color\.white, 100)' "$FILE" | grep -v 'COLOR_TRANSPARENT' | head -5)
if [ -n "$HARD_TRANS" ]; then
    echo "WARNING: Hardcoded transparent color (use COLOR_TRANSPARENT):"
    echo "$HARD_TRANS"
    ((WARNINGS++))
fi

# Check max drawing objects declared
MAX_LINES=$(grep -o 'max_lines_count=[0-9]*' "$FILE" | head -1)
MAX_LABELS=$(grep -o 'max_labels_count=[0-9]*' "$FILE" | head -1)
MAX_BOXES=$(grep -o 'max_boxes_count=[0-9]*' "$FILE" | head -1)
echo ""
echo "Drawing limits: $MAX_LINES, $MAX_LABELS, $MAX_BOXES"

# --- SUMMARY ---
echo ""
echo "=== Results ==="
if [ "$ERRORS" -eq 0 ] && [ "$WARNINGS" -eq 0 ]; then
    echo "PASS - No issues found"
elif [ "$ERRORS" -eq 0 ]; then
    echo "PASS with $WARNINGS warning(s)"
else
    echo "FAIL - $ERRORS error(s), $WARNINGS warning(s)"
fi

exit $ERRORS
