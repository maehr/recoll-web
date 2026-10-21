# Agent Instructions: recoll-web

This repository builds recoll-web, a small FastAPI, Jinja2, and htmx web interface for an existing Recoll index.

The repository follows the shared
[Agents Tooling Specification](https://gist.github.com/maehr/6c48ef14f37c9f745fa1fbaa315d106b) for Python.
Sections 1, 3, 5, and 6 are unchanged. Sections 2 and 4 are narrowed to this repository. The specification
section on browser and WASM code does not apply, because no Python runs in the browser. Sections 7 to 9 are
specific to this repository. `README.md` is for users. This file is for work on the repository.

## 1. Orchestration

Context is the scarce resource. Manage it.

**Model tier.** A frontier model holds the plan, the decisions, and the shared context. A small model does a bounded subtask. Pick the tier before you spawn the agent.

**Delegate on evidence.** A subagent starts cold and derives the context again. Delegate work that reads far more than it reports: broad search, log triage, or fan-out over many files. Do a small local edit inline.

**Contracts, not conversations.** Give a subagent one task, the context it cannot infer, the output shape, and the stop condition. A subagent returns a conclusion, never a file dump. Verify a report before you act on it.

**Parallel only when independent.** Run agents at the same time only when no result feeds another. Use three at most.

**Context ladder.** At 25% of the window, name the source of the pressure. At 50%, reduce it: write state to disk, delegate the reading, or narrow the re-reads. At 75%, stop and reduce before further work.

**State on disk.** Write plans, findings, and decisions to files. The transcript dies at the next compaction.

**Read narrow.** Read the slice, not the file. After you write a file, verify the diff or the section you changed. Do not read the whole file again.

## 2. Tooling

Pin versions in `pyproject.toml`. Commit `uv.lock`. Install with `uv sync --locked`. Never ship a development tool to runtime.

**Development.** [uv](https://docs.astral.sh/uv/) dependencies, environments, and the lockfile · [ruff](https://docs.astral.sh/ruff/) lint and format · [ty](https://docs.astral.sh/ty/) types, pinned exactly while it stays in beta · [pytest](https://docs.pytest.org/) with [pytest-cov](https://pytest-cov.readthedocs.io/) tests, doctests, and coverage · [HTTPX2](https://github.com/pydantic/httpx2) for the FastAPI test client · [prek](https://prek.j178.dev/) hooks, with `prek.toml` · [commitizen](https://commitizen-tools.github.io/commitizen/) (`cz`) commits and SemVer bumps · [git-cliff](https://git-cliff.org/docs/) changelog.

**Runtime.** [FastAPI](https://fastapi.tiangolo.com/) with [uvicorn](https://www.uvicorn.org/) · [Jinja2](https://jinja.palletsprojects.com/) templates and [MarkupSafe](https://markupsafe.palletsprojects.com/) · [Pydantic](https://pydantic.dev/) v2 for the query parameters · [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) configuration · [Typer](https://typer.tiangolo.com/) CLI · [htmx](https://htmx.org/) 2, vendored in `src/recoll_web/static/` · the Recoll Python module, which comes with Recoll and is not on PyPI.

Keep the runtime small. Use stdlib `logging`, not structlog: the code logs one event. Do not add a database, a dataframe, a notebook, or a chart library. Do not add a browser build step.

## 3. Standards

* [SemVer 2.0.0](https://semver.org/) for versions.
* [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) for commit messages.
* [Contributor Covenant 3.0](https://www.contributor-covenant.org/version/3/0/code_of_conduct/) as `CODE_OF_CONDUCT.md`.
* [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.en.html) as `LICENSE`. SPDX identifier `AGPL-3.0-only`.

## 4. Code

* Use a type hint everywhere.
* Use Pydantic at an I/O boundary only: the query parameters in `web.py` and `Settings`.
* Use a dataclass for an internal carrier. Keep core logic in pure functions in `core.py`.
* Call the Recoll module only from `recoll_backend.py`. Pass the module as an argument, so that a test can pass a fake.
* Keep `create_app()` free of global state. A route is a closure over the settings and the backend.
* Put a runnable example in the docstring of each public function and class.
* Require 100% coverage. Keep each exclusion narrow and explicit. `load_recoll()` is the only one.
* Add a case to the fake Recoll module in `tests/conftest.py` when the code uses a new part of the Recoll API. Make the fake behave as the real module does. Prove it in `tests/test_integration.py`.
* Run the gate below through `prek`, with a `cz` `commit-msg` hook. Let `git-cliff` write the changelog.

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check
uv run pytest --doctest-modules --cov --cov-fail-under=100
```

`pyproject.toml` adds `--doctest-modules` by default. `uv run prek run --all-files` runs the full gate.

## 5. GitHub Workflow

Use a fork and a pull request. Never push to upstream.

```bash
gh repo fork OWNER/REPO --clone
git switch -c feat/thing
gh pr create --repo OWNER/REPO
```

Allow maintainer edits. Resync with `gh repo sync`. Put one logical change in one PR. Title the PR with a Conventional Commit.

**Stacked PRs.** Each PR targets the branch below it. The bottom PR targets the trunk. Merge from the bottom up. GitHub retargets the rest. Take the requirements from the trunk only. Use the `gh stack` extension. Keep a stack in one repository, never across forks.

**Trunk protection.** Both layers are idempotent, so a second run converges.

```bash
gh repo edit --enable-squash-merge --enable-merge-commit=false --enable-rebase-merge=false \
  --delete-branch-on-merge --allow-update-branch \
  --enable-secret-scanning --enable-secret-scanning-push-protection
gh api -X PUT repos/OWNER/REPO/branches/main/protection --input protection.json
```

The `PUT` replaces the whole configuration. Take the body shape from the [API reference](https://docs.github.com/en/rest/branches/branch-protection), not from a stale snippet.

For a repository with more than one maintainer, enforce a PR before a merge, at least one approval, dismissal of a stale approval on push, code-owner approval, last-push approval, conversation resolution, strict status checks, linear history, `enforce_admins: true`, no force-push, and no deletion. A solo repository differs. See the bullets below.

* Without `enforce_admins`, the rule is advisory for whoever can bypass it.
* A solo repository needs three settings together: 0 required approvals, no required code-owner review, and no required last-push approval. You cannot approve your own pull request, so either of the last two deadlocks the merge even at 0 approvals.
* The free plan covers branch protection on a public repository. Branch protection on a private repository needs Pro.
* Plan limits differ per feature. Secret scanning, push protection, CodeQL, and dependency review are free on a public repository. On a private repository each one needs a paid GitHub security plan. Check the plan before you enable one in a workflow or in `gh repo edit`.
* Rulesets are the successor at organization scale. `gh ruleset` only reads, and creation uses `POST`, so a second run duplicates the ruleset. Prefer the `PUT` for one repository.

## 6. CI/CD Security

Follow [secure use of Actions](https://docs.github.com/en/actions/reference/security/secure-use).

* Set `permissions: contents: read` at the top level. Widen it per job only where a job needs more.
* Default the repository token to read: `gh api -X PUT repos/OWNER/REPO/actions/permissions/workflow -f default_workflow_permissions=read`.
* Pin an action to a full commit SHA. Verify the SHA against the upstream repository, not a fork. Let Dependabot bump it.
* Never check out fork code under `pull_request_target`. Prefer `workflow_run`, and treat its artifacts as untrusted.
* Never interpolate `github.event.*` into `run:`. Pass the value through `env:` and quote `"$VAR"`.
* Use OIDC and a short-lived cloud role. Do not store a long-lived secret. Keep a secret a scalar, never a JSON blob. Rotate it.
* Gate a deploy on an Environment with required reviewers. Prefer an environment secret over a repository secret.
* Do not use a self-hosted runner on a public repository.
* Cover `.github/workflows/**` in `CODEOWNERS`.
* Require the section 4 gate, CodeQL, and `dependency-review-action`. Run the same gate locally, so CI gives no surprise. On a private repository, confirm the plan covers CodeQL and dependency review first.

## 7. Layout

| Path | Content |
| --- | --- |
| `src/recoll_web/core.py` | Pure functions and the data carriers: the query, paging, IDs, highlighting, and text |
| `src/recoll_web/recoll_backend.py` | The only module that calls Recoll, and the protocols that type the native module |
| `src/recoll_web/web.py` | `Settings`, the query parameters, `create_app()`, and the routes |
| `src/recoll_web/cli.py` | The Typer command and the ASGI factory `build_app()` |
| `src/recoll_web/templates/` | `index.html`, and the fragments `_results.html` and `_preview.html` |
| `src/recoll_web/static/` | `styles.css`, `app.js`, and the vendored `htmx.min.js` with its licence |
| `tests/conftest.py` | The fake Recoll module and the stub backend |
| `tests/test_integration.py` | The tests against the real Recoll module, marked `recoll` |
| `.github/workflows/` | CI, CodeQL, and the PyPI release |

## 8. Recoll traps

These behaviors of the Recoll Python module shape the code. Keep the fix when you change the code. `tests/test_integration.py` proves the first four against Recoll 1.44.

| Trap | Fix |
| --- | --- |
| `makedocabstract()` escapes `<` and `&`, also with `nohl=True` | `recoll_text()` unescapes once, then the template escapes once |
| `Query.highlight()` turns line breaks into `<br>` and can put the markers around the tags | `mark_terms()` marks the terms from `Query.getgroups()` in Python |
| `Doc.url` holds `file://` and the raw path, without percent-encoding | `display_path()` removes the prefix. It does not parse a URL. |
| `Db.getDoc()` returns an empty document for an unknown ID | `find_doc()` treats a document without `url` as not found |
| Older Recoll versions have `Extractor` in `rclextract` only. Recoll 1.44 has it in both modules. | `load_recoll()` imports both modules |
| `recoll.rclconfig` does not import in 1.44 | `parse_topdirs()` reads `recoll.conf` itself |
| The docstring of `sortby()` requires the call before `execute()` | `search()` sorts first |
| The native module gives no thread-safety guarantee | Each call opens its own read-only connection |

## 9. Test against real Recoll

The integration tests need the Recoll module and `recollindex`. They build a temporary index of synthetic files. Never use real documents as test data.

1. Make the Recoll module visible to the venv Python. On Debian and Ubuntu, run `uv venv --system-site-packages` with `UV_PYTHON=/usr/bin/python3`.
2. Put the folder that holds `recollindex` on `PATH`.
3. Run `uv run pytest -m recoll`.

On the maintainer's Mac, Recoll comes from the source build in `~/src/oberon-plus-search`:

```bash
O=~/src/oberon-plus-search
PYTHONPATH=$O/.venv/lib/python3.15/site-packages PATH=$O/.recoll/1.44.2/bin:$PATH \
  uv run --no-sync pytest -m recoll
```

The Python of this venv and of that venv must have the same version. `.python-version` holds 3.15 for this reason.
