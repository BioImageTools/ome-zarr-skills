# Inspect an image URL before conversion

Use bounded metadata reads to determine whether a URL can supply a useful
conversion plan before downloading image pixels. Use
[**bia-remote-metadata**](https://github.com/BioImage-Archive/bia-remote-metadata),
Python package `bia_remote_metadata` and CLI `bia-remote-metadata`.
Instructions below were checked against version 0.29.0, result schema 19,
checkout revision `c6e73777b01d06edc72ee01f913d8dcf753d6501`.

## Run a bounded probe

Locate the installed command or supplied project checkout. Read
`bia-remote-metadata --help` and `--schema` for that version. A checkout can be
used through its existing environment or `uv run --project /path/to/checkout
bia-remote-metadata ...`; dependencies require Python >=3.12 for the verified
version. If a checkout is needed, use the official repository and its installation
instructions rather than assuming a package-registry release:

```bash
git clone git@github.com:BioImage-Archive/bia-remote-metadata.git
```

HTTPS clone URL: `https://github.com/BioImage-Archive/bia-remote-metadata.git`.
Record the revision actually used; the verified revision above documents the
API checked when this guidance was written, not a requirement to use an old release.

For a known image URL, use default **probe** mode:

```bash
bia-remote-metadata \
  --max-bytes 8388608 --max-requests 100 --timeout 30 --concurrency 1 \
  "https://example.org/image.czi" > "/data/image.remote-inspection.json"
```

Replace the URL and use a fresh report path. These are per-URI limits: 8 MiB
of response bodies, 100 requests, and 30 seconds. They are not a prediction
of the image's size. Capture exit status and stderr separately. The CLI emits
a JSON **list**, including for one URL. Exit 1 means at least one probe failed;
exit 2 indicates invalid invocation/configuration. Check each result's status
and the expected result count; exit 0 also permits an empty input list.

For batches, `--stdin` accepts a JSON list of URLs. The Python equivalent is
`bia_remote_metadata.probe_images(uris, options=ProbeOptions(...))` with
`max_bytes_per_uri`, `max_requests_per_uri`, `timeout_seconds_per_uri`, and
`max_concurrency`. Avoid mixing the CLI flag names with Python option names.

`--inspect` and `--classify-only` use a different result schema. Classification
alone does not establish dimensions or dtype; prefer probe mode for this
workflow and do not parse classification results as `ProbeSuccess`.

## Turn successful metadata into a sizing input

Only use `status="ok"` results with a supported schema. For each selected
entry in `series`, extract:

| Field | Use |
| --- | --- |
| `series_id`, `name`, `role` | Inventory all images; distinguish primary images, overviews, labels, and thumbnails. Do not assume IDs are Bio-Formats `--series` indices. |
| `dimensions.T/C/Z/Y/X` | Construct named logical TCZYX dimensions; never depend on JSON property order. Report five logical axes, singleton axes, and non-singleton count. Source storage rank/order can remain unknown. |
| `dtype` | Compute storage bytes per scalar sample, e.g. uint16=2, float32=4; significant bits do not replace storage bytes. |
| `samples_per_pixel` | Preserve RGB/RGBA samples separately from logical channels until output mapping is confirmed. |
| `axis_interpretation`, `dimensions_basis`, `frame_dimensions`, `extra_dimensions` | Explain the reader's interpretation and any extra acquisition axes. |
| `phase_mapping`, `sparse_coverage`, `spatial_bounds` | Preserve phase folding, missing-plane fill, and frame/canvas distinctions; do not substitute spatial bounds for output dimensions. |
| `resolutions` | Existing levels, not independent source series. |
| `physical_pixel_sizes` | Calibration only when present; null is unknown, never a physical size of 1. |

For scalar data, the candidate output shape is `(T,C,Z,Y,X)`. For verified
converter sample separation, use `C_out=C*samples_per_pixel` and keep dtype
unchanged. For example logical `C=1`, uint8, `samples_per_pixel=3` becomes
three uint8 output channels, not one 24-bit scalar. Do not multiply twice
if a reader already reports separated output channels. Check RGB/RGBA warnings
and converter compatibility before applying that mapping.

Inspect `warnings`, `validation`, optional `sampling`, and
`provenance.interpretation_profile`. Default probing is conservative. Select an
opt-in profile only for its documented layout and matching converter semantics;
do not switch profiles until a failed probe returns convenient dimensions.
Profiles can fold phases or other acquisition axes into T: such T is not
necessarily elapsed time and must not be assigned fabricated time calibration.

Record `schema_version`, tool/reader versions, effective budgets, source byte
size, ETag/Last-Modified where supplied, and `metrics`. Source byte size is
compressed-file size, not uncompressed array bytes. Metrics with
`complete=false` are incomplete counters, not proof that a full probe finished.
Protect signed URL query parameters when presenting or sharing reports; the
JSON includes source URLs.

Feed the reconciled output shape and dtype into
[DCA storage planning](storage-planning.md). Report proposed inner chunks,
outer shards, their bytes, and converter route per image. Mark the plan as
based on remote metadata, with pixel checks and absent calibration pending.

## Handle unsupported sources and hand off to conversion

The verified version supports HTTP/HTTPS partial reads for specific layouts,
not every Bio-Formats format. It does not automatically follow redirects,
support FTP or URI user-info authentication, or fall back to full downloads.
Signed query URLs can be used. Consult its installed `COVERAGE.md` for format
boundaries. Do not assume a remote probe failure means Bio-Formats cannot read
the downloaded file.

On `status="error"`, retain the error code and stage. Do not use diagnostics
as usable image dimensions. For `budget_exceeded` or timeout, consider one
targeted retry with a justified bounded increase; for source changes,
unsupported layouts, missing companions, or unavailable range reads, resolve
the cause or use local inspection. Do not retry indefinitely or quietly
download the whole source during a metadata-only request.

Supply known authorized companion URLs only through supported options such as
`--companion-uri` for the documented Micro-Manager indexed workflow. Do not
guess sibling URLs or interpret one fragment as a complete acquisition.

For an authorized conversion, stage the complete fileset in a fresh local
location with enough space, retaining filenames and companion relationships.
Compare available validators and byte sizes against the inspected source;
if identity or local metadata differs, inspect again and recalculate the plan.
Byte length alone does not establish identity. Reconcile local Bio-Formats
series numbering, dtype, sample separation, and dimensions, then read bounded
pixels before conversion. Pass the staged local entrypoint to bioformats2raw;
the remote probe provides no converter streaming support.

## Source provenance

The official repository is
[BioImage-Archive/bia-remote-metadata](https://github.com/BioImage-Archive/bia-remote-metadata).
The API above was verified against a local checkout. Its `README.md`, `COVERAGE.md`, `docs/spec.md`,
`src/bia_remote_metadata/models.py`, and `src/bia_remote_metadata/cli.py`
define the contract above. Use these files from the installed/supplied checkout
when checking a different version.
