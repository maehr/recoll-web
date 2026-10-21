# Contribute to recoll-web

This guide explains how to propose a change to recoll-web. Read it before you open a pull request.

## Before you start

- Read the [Code of Conduct](CODE_OF_CONDUCT.md). It applies to every project space.
- Open an issue before you start a large change. A small fix needs no issue.
- Report a security issue in private. See [SECURITY.md](SECURITY.md).

## Set up the project

You need [uv](https://docs.astral.sh/uv/) and Git.

1. Install the locked dependencies: `uv sync --locked`.
2. Install the Git hooks: `uv run prek install`.

The integration tests need the Recoll Python module. Section 9 of [AGENTS.md](AGENTS.md) describes how to run them.

## Make a change

1. Fork the repository and clone it: `gh repo fork maehr/recoll-web --clone`.
2. Create a branch for the change. For example: `git switch -c feat/search-filter`.
3. Make one logical change on the branch.
4. Run the gate: `uv run prek run --all-files`.
5. Commit the change with a Conventional Commit message.
6. Push the branch to your fork.
7. Open a pull request against `main`.

The gate runs these checks:

- Lint and format with ruff.
- Type check with ty.
- Run the tests with pytest, and require 100% coverage.

Each check must pass before you open a pull request. The continuous integration runs the same gate.

## Pull requests

- Put one logical change in each pull request.
- Title the pull request as a Conventional Commit. For example: `fix: escape the preview title`.
- Describe what the change does and why it is needed.
- Keep the option that allows edits by maintainers turned on.

The maintainer reviews every change. Each change to a workflow needs the maintainer review.

## Code rules

- Call the Recoll module only from `src/recoll_web/recoll_backend.py`.
- Use a type hint everywhere in the Python code.
- Use synthetic files for tests. Never use real documents as test data.
- Keep the coverage at 100%. Keep each coverage exclusion narrow and explicit.

## License

Each contribution uses the license of the project, AGPL-3.0-only. See [LICENSE](LICENSE).
