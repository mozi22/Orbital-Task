# Issue → Branch → PR Workflow

This is the standing convention for this project, effective now and for all future work. Every contributor (human or agent) follows it.

## 1. One issue, one branch, one PR

- Every piece of work starts as a **GitHub issue**. No branch is created before its issue exists.
- Each issue gets exactly **one linked branch**, created from that issue (GitHub's "create a branch" on the issue, or `issue-<number>-<short-slug>` if created manually). All commits for that work land on this branch — never directly on `main`.
- The branch is closed out by exactly **one pull request** back into `main`. A branch is merged once, then deleted (local and remote).
- If new findings come up after opening the PR (e.g. review feedback), fix them with **new commits on the same branch** — don't open a second branch or a second PR for the same issue.

## 2. What an issue must contain

Every issue must clearly state, before work starts:

- **Reason** — why this work exists: the problem it solves or the goal it serves, not just a feature name.
- **Acceptance criteria** — a concrete, checkable list of what "done" means. Vague issues don't get branches.

An issue may also link a PRD (`docs/prds/*.md`) or the relevant requirements doc for deeper context, but the issue itself must still restate reason + acceptance criteria — a reader shouldn't need to open another file to know when the issue is resolved.

## 3. PR labeling: `critical` / `non-critical`

Every PR gets exactly one of these two labels:

- **`critical`** — the PR touches a path listed in [`docs/project/CRITICAL_PATHS.md`](project/CRITICAL_PATHS.md).
- **`non-critical`** — everything else.

The label is decided **deterministically from the paths changed**, per that doc's table — not from a subjective read of "how risky does this feel." It is **purely informational** for whoever is deciding what to merge and when; it is never used by any agent as a merge gate or an excuse to block/require extra approval automatically.

## 4. Lifecycle summary

1. Issue created (reason + acceptance criteria) — optionally against a milestone.
2. Branch created from the issue.
3. Work happens as commits on that branch only.
4. PR opened from the branch, description covers what/why/how it was verified, labeled `critical` or `non-critical`.
5. Review happens on the PR (findings recorded in the PR description, not a separate doc).
6. PR merges into `main`.
7. Branch deleted, both remote and local, once merge is confirmed. Prefer the host's "auto-delete head branches" setting for the remote side so this doesn't need repeating manually per issue.

## 5. Milestones

Large bodies of work (e.g. this project's Milestone 1, Milestone 2) are tracked as GitHub **milestones**, with individual issues assigned to the milestone they belong to. A milestone is done when all its issues are closed and merged.
