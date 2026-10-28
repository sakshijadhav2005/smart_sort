# SortSmart

A reusable file intake engine. SortSmart detects each file's **real type from
its content** (magic bytes, not the extension), catches **duplicates**
(SHA-256) and **corrupt or disguised files**, sorts files into
`Images / Videos / Audio / Documents / Archives / Others`, and records every
move in a **SQL catalog** so each one can be searched, reported on and undone.

You can use the same engine two ways, and it gives the same result for a given file whichever you pick:

| You are | Use |
|---|---|
| Someone with a messy Downloads folder | `sortsmart watch` (CLI / background service) |
| A Python developer | `from sortsmart import Sorter` |
| A plugin author | Drop a `.py` file into `plugins/` |
| Support / ops | Structured logs, `sortsmart health`, `sortsmart restore` |

```
inbox ─► watcher (waits for stable size) ─► detect type + SHA-256
           ├─ invalid (0-byte, corrupt, extension lies) ─► Quarantine/   (reason logged)
           ├─ seen before (same SHA-256)                ─► Duplicates/
           └─ otherwise: plugins ─► YAML rules ─► category [/YYYY/MM]
every move ─► SQL catalog + JSON logs ─► search · stats · restore · dashboard
```

SortSmart moves files and never deletes or overwrites them. Name clashes become `name (1).ext`.

## Install

```bash
pip install .            # core: CLI + library
pip install ".[dashboard]"   # + Streamlit dashboard
pip install ".[pdf]"     # better PDF text extraction for plugins (optional)
```

Python 3.9+. Type detection is pure Python. If `python-magic` is installed
(`.[magic]`), SortSmart uses it only as a fallback for formats it has no
signature for.

## CLI

```bash
sortsmart watch ~/Downloads --config rules.yaml    # sort new files as they arrive
sortsmart sort ./inbox -r                          # one-off sort of a folder
sortsmart classify file123                         # type, hash, validity; moves nothing
sortsmart restore --last 10                        # undo the 10 most recent moves
sortsmart restore --id 42 43
sortsmart stats                                    # counts, storage by type, space saved
sortsmart search --type pdf --name invoice
sortsmart health                                   # exit code 0 ok, 2 degraded
sortsmart dashboard                                # Streamlit dashboard
```

Add `--json` to any command to get machine-readable output. The config is taken from `--config`,
then `$SORTSMART_CONFIG`, then `./rules.yaml`. If no destination is configured,
files go to `<inbox>/Sorted`.

When you restore a file into a watched inbox, it stays there and is not sorted again.

## Library

```python
from sortsmart import Sorter

sorter = Sorter(config="rules.yaml")          # or a dict, or nothing for defaults
result = sorter.process("uploads/file123")
print(result.category, result.destination, result.status)   # Images .../Images/file123 sorted

sorter.detect_type("uploads/file123")   # "png": type only, nothing moved
sorter.is_duplicate("uploads/file123")  # hash check only
sorter.classify("uploads/file123")      # full decision (type, hash, valid, reason, folder), no move
sorter.restore(result.id)
sorter.search(category="Videos"); sorter.stats(); sorter.health()
sorter.close()                          # or: with Sorter(...) as sorter:
```

`result.status` is one of `sorted`, `duplicate`, `quarantined`, `failed` (the move failed after
retries, so the file stays where it was) or `skipped`.

### Docker

```bash
docker build -t sortsmart .
docker run -d -v "$PWD/data:/data" sortsmart
```

The container watches `/data/inbox`, sorts into `/data/sorted`, and keeps its catalog and logs in `/data`
(see [`docker/rules.yaml`](docker/rules.yaml)).

## Configuration (`rules.yaml`)

See the annotated [`rules.yaml`](rules.yaml). The main settings:

* `date_subfolders: true` turns on folders like `Images/2026/10`. The date comes from the file's mtime, or from processing time if you set `date_source: processed`.
* `categories:` moves a type or extension to another category, or to a new one, for example `Code: [py, js]`.
* `rules:` are custom rules, checked in order after plugins and before the default categories:
  ```yaml
  rules:
    - name: bank-statements
      match: {type: pdf, name_contains: [statement]}
      destination: Documents/Statements
  ```
  Conditions: `type`, `category`, `extension`, `name_contains`, `name_glob`, `name_regex`,
  `text_contains`, `min_size_mb`, `max_size_mb`.
* `quarantine_mismatch` decides whether a file whose extension claims a different known format goes to quarantine. Unknown extensions are never treated as a mismatch.
* `ignore:` lists name patterns that are never touched (`*.part`, `*.crdownload`, ...).
* `stability`, `retry`, `logging` and `health` are tuning settings.

## Plugins

```python
from sortsmart.plugins import Detector

class InvoiceDetector(Detector):
    name = "invoice"

    def matches(self, file):
        return file.type == "pdf" and "invoice" in file.text.lower()

    def destination(self, file):
        return "Documents/Invoices"
```

* A **Detector** decides whether a file matches and where it goes. Detectors run before the YAML rules, and the first match wins.
  `file` has `name, ext, type, mime, category, size, hash, path` and a lazy `text`
  (text files, PDF, DOCX/PPTX/XLSX).
* An **Action** has `run(result, file)`, which runs after a file is handled (filter which ones with `events`), and
  `alert(message, details)`, which runs when a health check turns unhealthy.
* `setup(self, settings)` receives `plugins.settings.<name>` from the config.
* Plugins are loaded from `plugins.dir` at startup. Built-in examples are enabled with
  `plugins.builtin: [invoice, screenshot, slack_alert]`.
* A plugin that raises an error is disabled and logged, and sorting carries on. `sortsmart health` lists disabled plugins.
  Plugins run with full Python access, so only load plugins you trust.

## Running as a service

* Linux (systemd): `sudo ./service/install_linux.sh /path/to/rules.yaml`
  (or adapt [`service/sortsmart.service`](service/sortsmart.service)).
* Windows (scheduled task that starts at logon and restarts on failure):
  `.\service\install_windows.ps1 -Config C:\path\rules.yaml`. Remove it with `uninstall_windows.ps1`.

## Operations

* **Logs**: JSON lines in `logging.dir/sortsmart.log`, rotated by size. Each line has
  `time, level, event, file, destination, hash, reason, ...`. Sorted files are logged at INFO,
  duplicates and quarantined files at WARNING, and failures at ERROR.
* **Catalog**: SQLite table `files` with columns `id, name, type, mime, category, size, hash, old_path,
  new_path, status, reason, plugin, duplicate_of, created_at, restored_at, restored_path`.
  A row is written before each move and finalized after it. If the process crashes mid-move, the
  row is reconciled on the next start.
* **Health**: checks the catalog, free disk space, watcher queue backlog, and files stuck in the inbox
  longer than `health.stuck_after` seconds. While watching, problems are logged and sent to
  Action plugins (for example Slack) once per incident.
* **Locked files**: moves are retried (`retry.attempts`). If a move still fails, the file is recorded as `failed` and
  left in place, and the next pass picks it up again.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The test suite covers detection for every format, validation, duplicates, quarantine,
restore, rules, plugins, the CLI and the watcher. It also has one test per PRD success metric in
[`tests/test_success_metrics.py`](tests/test_success_metrics.py):
≥98% accuracy on a mixed 500-file set, 100% of renamed files caught, under 5 s per file, no duplicate stored twice,
100% of moves restorable, the same result from CLI and library, a plugin in under 20 lines, and a crashing plugin
never stopping the core.

## Project layout

```
sortsmart/
  core/        detection, hashing, validation, rules, mover, engine, health
  catalog/     SQLite catalog and JSON logging
  plugins/     plugin interface, loader, built-in plugins
  cli.py       command-line tool
  watcher.py   folder watcher
  dashboard.py Streamlit dashboard
service/       systemd and Windows setup
plugins/       drop-in plugin folder
tests/
rules.yaml
```

## Not in v1

Cloud storage sync, AI image recognition and antivirus scanning are out of scope for v1; suspicious files are only quarantined.
The catalog uses portable SQL, but the planned switch to SQL Server Express (v3) is not implemented yet.
