---
name: close-stage
description: Use before marking a roadmap stage done or opening/merging its PR in this project (e.g. "mark stage X done", "let's open the PR") — and proactively before opening any PR here, even unprompted. Enforces this repo's PR-size and review gates from CLAUDE.md.
---

# Close Stage

Every roadmap stage in this project (root `CLAUDE.md`) closes the same way:
verify, review, then PR. This skill turns each gate into an explicit step
instead of something to remember under momentum.

## Sequence

1. **Verify for real.** `cd backend && python -m pytest -q && ruff check .`. If
   the stage touches an LLM/RAG/DB layer, also exercise it end-to-end with a
   real provider call — CLAUDE.md requires having actually run whatever gets
   claimed as verified.

2. **Let the PR-size hook do its job.** A `PreToolUse` hook blocks
   `gh pr create` when the diff exceeds CLAUDE.md's line budget ("Git
   workflow" section). If it blocks, split into a PR chain instead of arguing
   with it: PR A → `main`, PR B branches off A's branch (not `main`) and
   targets it, PR C off B, and so on — each stays independently reviewable,
   merged in order once its base lands.

3. **Run `/code-review` before opening the PR, not after.** Fix what's real
   and cheap; surface genuine design trade-offs to the user instead of
   deciding for them.

4. **Update the roadmap checklist in `CLAUDE.md`**, and correct any
   collaboration-model ownership tag that ended up different from the
   original plan — note *why* in the PR description (step 6).

5. **Ask before touching git.** A real go-ahead, not "looks good." Steps 6
   (open the PR) and 8 (merge it) each need their own confirmation.

6. **Branch, commit, push, open the PR** (`gh pr create`) with a description
   that reads like real engineering work: what changed, why, how it was
   verified — never "Stage N done."

7. **Bind and watch CI via the `ccd_pr` tools** (`bind_pr`, `get_status`) —
   never poll `gh` or sleep-loop for status.

8. **On explicit merge confirmation**, squash-merge, delete the branch, then
   `git branch -D` / `git fetch --prune` / `git branch -a` to confirm a clean
   state.
