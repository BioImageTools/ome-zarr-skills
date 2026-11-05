# ome-zarr-skills

Agentic Skills for [OME-Zarr](https://ngff.openmicroscopy.org/).

## Skills

| Skill | Invoke | What it does |
|-------|--------|--------------|
| `setup-ome-zarr-skills` | `/setup-ome-zarr-skills`, by you only | Run once per repo. Records the spec version, RFCs in use, and imaging domain in `docs/agents/ome-zarr.md`. |
| `reading-ome-zarr-spec` | automatic | Infers the OME-Zarr version in play and fetches that version's spec from the official site. |

## How the skills compose

Per-repo preferences live in `docs/agents/ome-zarr.md`, written by `setup-ome-zarr-skills`. Every skill in this set follows one rule: read that file if it exists, infer from context if it doesn't. No skill requires setup to have run.

## Dev install

Symlink the skills into Claude Code so edits in this repo are picked up on the next session:

```bash
scripts/link-skills.sh              # all projects (~/.claude/skills)
scripts/link-skills.sh <project>    # one project (<project>/.claude/skills)
scripts/link-skills.sh --unlink     # remove
```

Don't combine this with a plugin install of the same repo, or every skill appears twice.

## License

See [LICENSE](LICENSE).
