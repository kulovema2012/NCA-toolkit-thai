# Version Control for Error Resolution

This document provides guidelines for using Git version control to efficiently resolve errors in the NCA Toolkit Thai project.

## Table of Contents
- [Creating Checkpoints](#creating-checkpoints)
- [Working with Branches](#working-with-branches)
- [Making Focused Commits](#making-focused-commits)
- [Reverting Changes](#reverting-changes)
- [Using Stash for Temporary Changes](#using-stash-for-temporary-changes)
- [Comparing Different Approaches](#comparing-different-approaches)
- [Documenting Fixes](#documenting-fixes)
- [Finding When Bugs Were Introduced](#finding-when-bugs-were-introduced)
- [Common Error Resolution Commands](#common-error-resolution-commands)

## Creating Checkpoints

Before making changes to fix an error, create a checkpoint you can return to:

```bash
# Before making any changes to fix an error
git add .
git commit -m "Checkpoint before fixing [describe the error]"
```

## Working with Branches

Isolate your fixes in dedicated branches:

```bash
# Create a branch specifically for your fix
git checkout -b fix/descriptive-name

# Example
git checkout -b fix/srt-file-parameter
```

## Making Focused Commits

Make small, targeted commits that address specific issues:

```bash
# After making a specific change
git add path/to/changed/file.py
git commit -m "Clear description of the fix"

# Example
git add routes/v1/video/script_enhanced_auto_caption.py
git commit -m "Remove unsupported is_thai parameter from create_srt_file call"
```

## Reverting Changes

If your fix doesn't work or causes new problems, you have several options to revert:

### Option 1: Revert the most recent commit

```bash
git reset --hard HEAD~1
```

### Option 2: Revert a specific commit

```bash
# Find the commit hash
git log --oneline

# Revert the specific commit
git revert <commit-hash>
```

### Option 3: Discard all changes and return to the main branch

```bash
git checkout main
```

### Option 4: Discard changes to a specific file

```bash
git checkout -- path/to/file.py
```

## Using Stash for Temporary Changes

Try fixes without committing using Git's stash feature:

```bash
# Save your current changes
git stash save "Potential fix description"

# Apply the changes to test them
git stash apply

# Discard if they don't work
git stash drop
```

## Comparing Different Approaches

Create multiple branches to try different approaches:

```bash
# Create and switch to first approach branch
git checkout -b fix/approach-1
# Make changes, test

# Create and switch to second approach branch
git checkout main
git checkout -b fix/approach-2
# Make different changes, test

# Compare the two approaches
git diff fix/approach-1 fix/approach-2
```

## Documenting Fixes

Write detailed commit messages that explain:
- What the error was
- How you fixed it
- Why this approach works

Example:
```bash
git commit -m "Fix SRT file generation error

- Problem: create_srt_file() was being called with unsupported 'is_thai' parameter
- Solution: Removed parameter as Thai detection happens internally in wrap_thai_text()
- Tested with sample Thai script and confirmed subtitles generate correctly"
```

## Finding When Bugs Were Introduced

Use git bisect to find exactly when a bug was introduced:

```bash
git bisect start
git bisect bad  # Current version has the bug
git bisect good <older-commit-hash>  # This version worked
# Git will help you find exactly which commit introduced the bug
```

## Common Error Resolution Commands

### Check current status

```bash
git status
```

### View commit history

```bash
git log --oneline
```

### View changes in a file

```bash
git diff path/to/file.py
```

### Temporarily save changes

```bash
git stash
```

### Restore stashed changes

```bash
git stash pop
```

### Discard all local changes

```bash
git reset --hard
```

### Create a new branch for a fix

```bash
git checkout -b fix/issue-name
```

### Switch back to main branch

```bash
git checkout main
```

### Pull latest changes from remote

```bash
git pull origin main
```

### Push your fix to remote

```bash
git push origin fix/issue-name
```

### Revert to a specific commit

```bash
git reset --hard <commit-hash>
```

### Undo the last commit but keep the changes

```bash
git reset --soft HEAD~1
```

### Undo the last commit and discard changes

```bash
git reset --hard HEAD~1
```
