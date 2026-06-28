# KeloFred

> _Project description coming soon._

## Projects

- **[`keloray-control/`](./keloray-control/)** — a programmable controller for
  Keloray / Gizwits smart lights (cloud API): custom scenes & effects
  (including `thunderstorm` and a research-backed tropical-sun tracker),
  schedules/automations, and a REST API + web dashboard. Research notes for the
  sun tracker live in [`research/`](./research/).

## Status

This repository has its DevOps scaffolding (CI, repo hygiene files,
contribution templates, and a Claude Code SessionStart hook) in place, plus the
`keloray-control` application above.

## Getting started

The toolchain isn't pinned to a specific language yet. Once you add a
dependency manifest (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`,
etc.) the CI workflow and the SessionStart hook will auto-detect it and run the
appropriate install / lint / test steps. See the sections below to wire that up.

### Local development

```bash
# Clone
git clone https://github.com/fredparkvs/KeloFred.git
cd KeloFred

# Then, depending on the stack you choose, e.g.:
#   npm install        # Node / TypeScript
#   pip install -e .    # Python
#   go mod download     # Go
```

## Continuous integration

CI runs on every push and pull request via GitHub Actions
(`.github/workflows/ci.yml`). It auto-detects the project's stack and runs the
matching install, lint, and test commands. Until code exists, it passes as a
no-op.

## Contributing

1. Create a feature branch off `main`.
2. Make your changes with clear, focused commits.
3. Open a pull request using the provided template.

Issue and pull-request templates live under `.github/`.

## License

Released under the [MIT License](./LICENSE).
