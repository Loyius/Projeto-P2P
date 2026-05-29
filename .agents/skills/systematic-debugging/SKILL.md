---
name: systematic-debugging
description: Use when encountering any bug, test failure, or unexpected behavior, before proposing fixes
---

## Overview
Random fixes waste time and create new bugs. Quick patches mask underlying issues.

**Core principle:** ALWAYS find root cause before attempting fixes. Symptom fixes are failure.

**Violating the letter of this process is violating the spirit of debugging.**

## The Iron Law
```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If you haven't completed Phase 1, you cannot propose fixes.

## When to Use
Use for ANY technical issue: test failures, bugs, unexpected behavior, performance problems, build failures, integration issues.

**Use this ESPECIALLY when:** Under time pressure, "just one quick fix" seems obvious, you've already tried multiple fixes, previous fix didn't work, you don't fully understand the issue.

## The Four Phases
You MUST complete each phase before proceeding to the next.

### Phase 1: Root Cause Investigation
**BEFORE attempting ANY fix:**

1. **Read Error Messages Carefully** — Don't skip past errors or warnings. Read stack traces completely.
2. **Reproduce Consistently** — Can you trigger it reliably? If not reproducible → gather more data, don't guess.
3. **Check Recent Changes** — What changed? Git diff, recent commits, new dependencies, config changes.
4. **Gather Evidence in Multi-Component Systems** — Add diagnostic instrumentation at each component boundary. Log what enters and exits. Run once to gather evidence showing WHERE it breaks. THEN analyze.
5. **Trace Data Flow** — Where does bad value originate? Trace up the call stack until you find the source. Fix at source, not at symptom.

### Phase 2: Pattern Analysis
1. **Find Working Examples** — Locate similar working code in same codebase.
2. **Compare Against References** — Read reference implementation COMPLETELY.
3. **Identify Differences** — List every difference, however small.
4. **Understand Dependencies** — What other components, settings, config, environment?

### Phase 3: Hypothesis and Testing
1. **Form Single Hypothesis** — State clearly: "I think X is the root cause because Y"
2. **Test Minimally** — Make the SMALLEST possible change to test hypothesis. One variable at a time.
3. **Verify Before Continuing** — Did it work? Yes → Phase 4. No → form NEW hypothesis. DON'T add more fixes on top.

### Phase 4: Implementation
1. **Create Failing Test Case** — Simplest possible reproduction. MUST have before fixing.
2. **Implement Single Fix** — Address the root cause. ONE change at a time. No "while I'm here" improvements.
3. **Verify Fix** — Test passes? No other tests broken? Issue actually resolved?
4. **If Fix Doesn't Work** — STOP. If < 3 tries: Return to Phase 1. **If ≥ 3: Question the architecture.**
5. **If 3+ Fixes Failed** — Each fix revealing new problem = architectural issue. Discuss with human before attempting more fixes.

## Red Flags - STOP and Follow Process
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Add multiple changes, run tests"
- "I don't fully understand but this might work"
- "One more fix attempt" (when already tried 2+)
- Proposing solutions before tracing data flow
- Each fix reveals new problem in different place

**ALL of these mean: STOP. Return to Phase 1.**

## Common Rationalizations
| Excuse | Reality |
|--------|---------|
| "Issue is simple, don't need process" | Simple issues have root causes too. |
| "Emergency, no time for process" | Systematic debugging is FASTER than guess-and-check. |
| "Just try this first, then investigate" | First fix sets the pattern. Do it right from the start. |
| "One more fix attempt" (after 2+ failures) | 3+ failures = architectural problem. |

## Quick Reference
| Phase | Key Activities | Success Criteria |
|-------|---------------|------------------|
| **1. Root Cause** | Read errors, reproduce, check changes, gather evidence | Understand WHAT and WHY |
| **2. Pattern** | Find working examples, compare | Identify differences |
| **3. Hypothesis** | Form theory, test minimally | Confirmed or new hypothesis |
| **4. Implementation** | Create test, fix, verify | Bug resolved, tests pass |

## Supporting Techniques
- **`root-cause-tracing.md`** - Trace bugs backward through call stack
- **`defense-in-depth.md`** - Add validation at multiple layers
- **`condition-based-waiting.md`** - Replace arbitrary timeouts

**Related skills:**
- **superpowers:test-driven-development** - For creating failing test case (Phase 4, Step 1)
- **superpowers:verification-before-completion** - Verify fix worked before claiming success
