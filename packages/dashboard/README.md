# dashboard: the kit every dashboard's site is made of

A dashboard turns its own runs into **blobs** (the JSON its page reads) and
**tables** (the rows of its download). The kit does the rest, and knows nothing
about forecasts. Stdlib only.

```python
from dashboard import page, download, site

html = page.render("web/", {"EEAI": blob})                 # chunks in manifest order, data spliced in
names = download.bundle("site/data.zip", [                 # the zip behind "Download data"
    ("README.md", readme),
    ("forecasts.csv", download.csv_text(columns, rows)),
    ("runs/2026-11-11.jsonl", Path("results/runs/2026-11-11.jsonl")),
])
site.write_site("site/", html, assets={"web/img": "web/img"})
site.verify("site/", required=("data.zip",))               # raises unless complete
site.snapshot("site/", files=("data.zip",))                # what it publishes, hashed
```

| | in | out |
|---|---|---|
| `page.render` | a source directory, `{NAME: blob}` | the page's text |
| `page.splice` | a page's text, a name, a blob | the text with that blob replaced |
| `page.blocks` | a published page's bytes | `{NAME_DATA: the block's bytes}` |
| `page.swap_frontend` | a new page, the published page | the new page around the published data, byte for byte |
| `download.csv_text` | columns, rows | CSV text |
| `download.bundle` | a path, `[(name, text, bytes or Path)]` | the zip's member names |
| `site.write_site` | a folder, the page's text, `{path in site: source dir}` | the folder |
| `site.verify` | a folder, required file names | nothing; raises if incomplete |
| `site.snapshot` | a folder, file names | `{blocks, files, sha256}` |

A page's source directory holds `manifest.json` (`{"chunks": [...], "blobs": [...]}`)
and the chunks. A blob `NAME` goes between `<!--NAME_DATA-->` and
`<!--/NAME_DATA-->` as `window.__NAME__`.

What a dashboard still writes itself: its questions and prompt, its run, the
view from its rows to blobs and tables, and the page's HTML, CSS and JS.

Users: `dashboards/airo` (`redlines.pages`, `redlines.hydrate`,
`redlines.export`), `dashboards/eeai` (`eeai.build`, `eeai.export`) and the
production scheduler (`packages/ops`), which reads published data through it.

## Pluggable question resolution

A dashboard chooses its own plug-ins and passes them to
`dashboard.resolutions.refresh(db, requests, resolvers, as_of=day)` from its
scheduled job. Forecast calls consume a saved input snapshot. A plug-in can
call a script or implement the Python protocol directly.

| Type | Role |
|---|---|
| `Target(question, horizon, version)` | Identity shared by forecasts of the same outcome. Each dashboard uses its own database. |
| `Request(target, resolver_id, rule, params)` | The versioned measurement rule and dashboard-owned parameters. |
| `Resolver.refresh(requests, *, as_of, after)` | Called once per registered resolver with a batch of requests and its last successfully committed JSON bookmark, initially `None`. Raise on source failure. |
| `RefreshBatch(observations, next_checkpoint)` | Zero or more observations per target. Return an empty batch when a successful check produces no evidence. |
| `Observation(target, revision, published_at, value, evidence)` | A stable source revision ID, ISO publication date or zoned timestamp (or `None`), numeric/boolean/categorical value, and JSON evidence. The store supplies the observation time. |
| `history(db, through=snapshot_id)` | Returns a snapshot ID and a mapping from targets to their effective observations in that snapshot. Omit `through` for the current snapshot. |
| `select(records, view)` | Selects `first_published`, `first_observed` or `latest` for scoring. An unknown publication date makes first-published selection unavailable. |

Use the selected observation's value with the forecast's metric. A probability
and a boolean outcome can feed a Brier score; EEAI uses signed errors for
median predictions. Aggregate each target once per named view.

Resolvers run outside the SQLite write lock. The store commits the observations
and checkpoints from all plug-ins together and rejects a stale concurrent
refresh. Re-reading a revision is idempotent. Changing evidence under the same
revision ID is a conflict. `correct` explicitly supersedes a mistaken record
and retains its lineage; previously issued snapshot IDs keep their old results.
