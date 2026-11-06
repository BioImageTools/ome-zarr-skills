# ome-zarr-skills

Agentic Skills for [OME-Zarr](https://ngff.openmicroscopy.org/).

## Install

Requires [Node.js](https://nodejs.org/en/download) (for `npx`). Then:

```bash
DISABLE_TELEMETRY=1 npx skills add BioImageTools/ome-zarr-skills -g
```

## Skills

| Skill | Invoke | What it does |
|-------|--------|--------------|
| `ome-zarr-primer` | automatic, loaded first | Background on bioimage analysis and OME-Zarr: image concepts, formats, Zarr chunks/shards, OME-Zarr layout and versions, tooling, pipelines, large-image patterns. The other skills build on it. |
| `setup-ome-zarr-skills` | `/setup-ome-zarr-skills`, by you only | Run once per repo. Records the spec version, RFCs in use, and imaging domain in `docs/agents/ome-zarr.md`. |
| `reading-ome-zarr-spec` | automatic | Infers the OME-Zarr version in play and fetches that version's spec from the official site. |
| `inspect-ome-zarr` | automatic | Read-only summary of an OME-Zarr store (local, zip, http, s3, gs): structure, axes, pixel size, pyramid, channels, storage, labels, plus anomalies with fixes. Optional JSON for other skills. |
| `planning-ome-zarr-layout` | automatic | Chooses chunk, shard and tile shapes from how downstream tools read and write the data (tiled segmentation, pixel classification, tracking, viewers, cluster jobs); spec rules such as DCA are applied afterwards. |

## How the skills compose

Per-repo preferences live in `docs/agents/ome-zarr.md`, written by `setup-ome-zarr-skills`. Every skill in this set follows one rule: read that file if it exists, infer from context if it doesn't. No skill requires setup to have run.

## Dev install

Symlink the skills into Claude Code (`.claude/skills`) and the cross-agent `.agents/skills` dir so edits in this repo are picked up on the next session:

```bash
scripts/link-skills.sh              # all projects (~/.claude/skills, ~/.agents/skills)
scripts/link-skills.sh <project>    # one project (<project>/.claude/skills, <project>/.agents/skills)
scripts/link-skills.sh --unlink     # remove
```

Don't combine this with a plugin install of the same repo, or every skill appears twice.

## License

See [LICENSE](LICENSE).
