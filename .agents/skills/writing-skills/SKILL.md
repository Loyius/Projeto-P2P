---
name: writing-skills
description: Use when creating new skills, editing existing skills, or verifying skills work before deployment
---

## Overview
**Writing skills IS Test-Driven Development applied to process documentation.**

You write test cases (pressure scenarios with subagents), watch them fail (baseline behavior), write the skill (documentation), watch tests pass (agents comply), and refactor (close loopholes).

**Core principle:** If you didn't watch an agent fail without the skill, you don't know if the skill teaches the right thing.

**REQUIRED BACKGROUND:** You MUST understand superpowers:test-driven-development before using this skill.

## What is a Skill?
A **skill** is a reference guide for proven techniques, patterns, or tools. Skills help future Claude instances find and apply effective approaches.

**Skills are:** Reusable techniques, patterns, tools, reference guides

**Skills are NOT:** Narratives about how you solved a problem once

## SKILL.md Structure
**Frontmatter (YAML):**
- Two required fields: `name` and `description` (max 1024 characters total)
- `name`: Use letters, numbers, and hyphens only (no parentheses, special chars)
- `description`: Third-person, starts with "Use when...", describes ONLY triggering conditions — **NEVER summarize the skill's process or workflow**

```markdown
---
name: Skill-Name-With-Hyphens
description: Use when [specific triggering conditions and symptoms]
---

# Skill Name

## Overview
What is this? Core principle in 1-2 sentences.

## When to Use
Bullet list with SYMPTOMS and use cases

## Core Pattern
Before/after code comparison

## Quick Reference
Table or bullets for scanning

## Common Mistakes
What goes wrong + fixes
```

## CSO: Description Field Critical Rules

**Description = When to Use, NOT What the Skill Does**

```yaml
# ❌ BAD: Summarizes workflow
description: Use when executing plans - dispatches subagent per task with code review

# ✅ GOOD: Just triggering conditions
description: Use when executing implementation plans with independent tasks in the current session
```

When the description summarizes the skill's workflow, Claude may follow the description instead of reading the full skill content.

## The Iron Law (Same as TDD)
```
NO SKILL WITHOUT A FAILING TEST FIRST
```

This applies to NEW skills AND EDITS to existing skills.

**No exceptions:**
- Not for "simple additions"
- Not for "just adding a section"
- Delete means delete

## Skill Creation Checklist (TDD Adapted)

**RED Phase - Write Failing Test:**
- [ ] Create pressure scenarios
- [ ] Run scenarios WITHOUT skill - document baseline behavior
- [ ] Identify patterns in rationalizations/failures

**GREEN Phase - Write Minimal Skill:**
- [ ] Name uses only letters, numbers, hyphens
- [ ] YAML frontmatter with `name` and `description`
- [ ] Description starts with "Use when..." — no workflow summary
- [ ] Address specific baseline failures
- [ ] Run scenarios WITH skill - verify agents comply

**REFACTOR Phase - Close Loopholes:**
- [ ] Identify NEW rationalizations from testing
- [ ] Add explicit counters
- [ ] Build rationalization table
- [ ] Re-test until bulletproof

## Common Rationalizations for Skipping Testing
| Excuse | Reality |
|--------|---------|
| "Skill is obviously clear" | Clear to you ≠ clear to other agents. |
| "Testing is overkill" | Untested skills have issues. Always. |
| "I'll test if problems emerge" | Test BEFORE deploying. |

**All of these mean: Test before deploying. No exceptions.**

## The Bottom Line
**Creating skills IS TDD for process documentation.**

Same Iron Law: No skill without failing test first.
Same cycle: RED (baseline) → GREEN (write skill) → REFACTOR (close loopholes).
