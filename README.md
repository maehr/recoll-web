# recoll-web

recoll-web is a small web interface for [Recoll](https://www.recoll.org/) full-text search. It reads an
existing Recoll index and never changes it. It uses FastAPI, Jinja2, and htmx, with no build step for the
browser code. It replaces [recoll-webui](https://github.com/koniu/recoll-webui).

## Features

- Search with the Recoll query language. The results update while you type.
- Filter by file category, by folder, and by date range.
- Sort by relevance, or by date in either direction.
- Read the snippets with the matched terms highlighted.
- Read the text of a document in a preview, also for a member of an archive or a mail folder.
- Get the results as JSON from `/api/search`.
- Download the original file, if you enable it.
- Use it without JavaScript. Each link and the search form also work as plain HTML.

## Requirements

- Recoll with its Python module. The module is not on PyPI. It comes with Recoll.
- A Recoll index. Make it with `recollindex` or with the Recoll GUI.
- Python 3.11 or later. It must be the Python that the Recoll module was built for.

## Install

The Python environment of recoll-web must see the Recoll module. A virtual environment does not see it
by default, so make it with the option `--system-site-packages`.

On Debian and Ubuntu:

```bash
sudo apt install recollcmd python3-recoll
pipx install --system-site-packages recoll-web
```

On another system, use the Python that Recoll uses:

```bash
python3 -c 'from recoll import recoll'
python3 -m venv --system-site-packages ~/.local/share/recoll-web
~/.local/share/recoll-web/bin/pip install recoll-web
```

If the first command fails, the Recoll module is not on the path of this Python. Find the folder that
holds the `recoll` package, and add that folder to `PYTHONPATH`. The
[macOS page of Recoll](https://www.recoll.org/pages/recoll-macos.html) describes this problem.

## Run

```bash
recoll-web
```

Then open <http://127.0.0.1:8080>.

recoll-web finds the Recoll configuration as Recoll does: the option `--confdir`, then `RECOLL_CONFDIR`,
then `~/.recoll`. It reads `topdirs` from `recoll.conf` and offers these folders in the folder filter.

| Option | Environment variable | Default | Effect |
| --- | --- | --- | --- |
| `--host` | `RECOLL_WEB_HOST` | `127.0.0.1` | The address that the server listens on |
| `--port` | `RECOLL_WEB_PORT` | `8080` | The port that the server listens on |
| `--confdir`, `-c` | `RECOLL_WEB_CONFDIR` | see above | The Recoll configuration folder |
| `--dir` | `RECOLL_WEB_DIRS` | `topdirs` | A folder for the folder filter and the download check. Repeat the option for more folders. The variable holds a JSON list. |
| `--allow-download` | `RECOLL_WEB_ALLOW_DOWNLOAD` | off | Serve the original files that are inside the folders |
| (none) | `RECOLL_WEB_PAGE_SIZE` | `20` | The number of results on a page |
| (none) | `RECOLL_WEB_PREVIEW_CHARS` | `45000` | The maximum length of a preview, in characters |
| (none) | `RECOLL_WEB_SOURCE_URL` | this repository | The source link in the page footer |

To run recoll-web under another ASGI server, use the application factory. The factory reads the
environment variables only:

```bash
uvicorn --factory recoll_web.cli:build_app --host 127.0.0.1 --port 8080
```

## Routes

| Route | Result |
| --- | --- |
| `GET /?q=…` | The search page. An htmx request gets the result list only. |
| `GET /preview/{id}?q=…` | The text of a document, with the terms of `q` highlighted |
| `GET /api/search?q=…` | The results as JSON. Each hit has `snippet` as text and `snippet_html` as safe HTML. |
| `GET /download/{id}` | The original file, as an attachment. Only with `--allow-download`. |

The search parameters are `q`, `category` (`text`, `spreadsheet`, `presentation`, `media`, `message`,
`other`), `dir`, `after` and `before` (dates as `YYYY-MM-DD`), `sort` (`relevance`, `newest`, `oldest`),
and `page`.

## Security

Keep the default address `127.0.0.1` unless you add access control in front of recoll-web. recoll-web
has no authentication. Each client that can reach it can read the titles, the paths, and the text of
all indexed documents. recoll-web prints a warning when you give it another address.

recoll-web protects the browser and the index in these ways:

- It opens the index read-only. It cannot start an index run.
- It escapes all document text. It never shows document HTML as HTML.
- It sends a strict Content Security Policy. The pages contain no inline script.
- It refuses a download outside the folders, also through a symbolic link.
- It sends each download as an attachment, so that a downloaded HTML file cannot run in the page.

## Migrate from recoll-webui

| recoll-webui | recoll-web |
| --- | --- |
| `webui-standalone.py` with an address and a port | `recoll-web --host ADDRESS --port PORT` |
| Folder filter from `topdirs` | The same, or `--dir` |
| Date range | `after` and `before` |
| Sort field and direction | `sort`: relevance, newest, or oldest |
| JSON and CSV export | JSON from `/api/search`. No CSV export. |
| Download of the original file | `--allow-download`, limited to the folders |
| Settings page with cookies | Command options and environment variables |
| Path translation for mounted folders | Not available |
| WSGI deployment | ASGI deployment, with the factory above |

## Develop

Prerequisite: [uv](https://docs.astral.sh/uv/).

1. Run `uv sync --locked`.
2. Run `uv run prek install`. The hooks run the quality gate and check each commit message.
3. Run `uv run prek run --all-files` to run the gate once.

The unit tests use a fake Recoll module. The doctests and the unit tests must cover 100% of the code.

The integration tests build a small index with `recollindex` and use the real Recoll module. They need the
Recoll module and `recollindex`. Without them, the tests skip. On Debian and Ubuntu:

```bash
export UV_PYTHON=/usr/bin/python3
uv venv --system-site-packages
uv sync --locked
uv run pytest -m recoll
```

With a Recoll build from source, add the folder that holds the `recoll` package to `PYTHONPATH`. Add the
folder that holds `recollindex` to `PATH`. Then run `uv run pytest -m recoll`.

Write each commit message as a [Conventional Commit](https://www.conventionalcommits.org/en/v1.0.0/).
`uv run cz commit` asks for the parts of the message.

## Release

1. Run `uv run cz bump`. It sets the next [SemVer](https://semver.org/) version from the commits. It
   writes `CHANGELOG.md` with git-cliff, then makes a signed commit and a signed tag.
2. Run `git push --follow-tags`.

The workflow `release.yml` builds the package for the tag and publishes it to PyPI.

## Publish

The repository is ready for GitHub and PyPI. Do these steps once, before the first release.

1. Make the repository: `gh repo create maehr/recoll-web --public --source . --push`.
2. Set the default token of the workflows to read-only:
   `gh api -X PUT repos/maehr/recoll-web/actions/permissions/workflow -f default_workflow_permissions=read`.
3. Protect the branch `main` as `AGENTS.md`, section 5, describes for a solo repository.
4. In the repository settings, make the environment `pypi`. Add yourself as a required reviewer.
5. On PyPI, add a pending trusted publisher with these values:

   | Field | Value |
   | --- | --- |
   | Project name | `recoll-web` |
   | Owner | `maehr` |
   | Repository | `recoll-web` |
   | Workflow | `release.yml` |
   | Environment | `pypi` |

6. Do the steps in [Release](#release).

## License

recoll-web is free software under the [GNU Affero General Public License v3.0](LICENSE)
(`AGPL-3.0-only`). If you run a changed version for other users over a network, you must offer them its
source code. The source link in the page footer does this. Set it with `RECOLL_WEB_SOURCE_URL`.

htmx is included in `src/recoll_web/static/` under the
[Zero-Clause BSD license](src/recoll_web/static/htmx.LICENSE).
