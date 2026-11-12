# Contributing

Thanks for helping improve Hatch.

1. Fork and create a branch from `main`.
2. Set up the environment as described in [docs/development.md](docs/development.md).
3. Make a focused change with tests. Golden template changes must pass
   `hatchctl templates lint`; code changes must pass `make lint` and `make test`.
4. Open a pull request describing the problem, the change and how you tested it.

## Template changes

Template, layer, compliance-rule and policy files are production configuration. A pull
request that changes them should state which devices are affected, include the rendered diff
for the example fixture (`hatchctl templates render <vendor>/<role>`), and bump `version` in
`template.yaml`. The owning team listed in `template.yaml` reviews it.

## Style

* Python: ruff (lint + format), mypy, type hints on public functions.
* TypeScript: strict mode, functional components and hooks.
* Commits: imperative subject line, one logical change per commit.
