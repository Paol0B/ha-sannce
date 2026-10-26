# Release

## What CI runs

This repository, `Paol0B/ha-sannce`:

| Workflow | When | What |
|---|---|---|
| `.github/workflows/ci.yml` | push and pull request to master, or by hand | `library`: pytest on `lib/tests` and `tests/docs`, Python 3.11 and 3.14. `quality`: a check that the `lib` commit is on master of `sannce-aio`, then `scripts/quality.sh` on Python 3.14. `hassfest`: `scripts/bench.sh hassfest`. `hacs`: HACS validation, category integration. |
| `.github/workflows/e2e.yml` | by hand only | `scripts/bench.sh test`: Home Assistant 2026.10.1 and the simulated camera in Docker, then the end-to-end suite and hassfest. It always runs `scripts/bench.sh down` after. A failed run uploads the Home Assistant log as the artifact `home-assistant-log`. |

The library repository, `Paol0B/sannce-aio`, runs the workflows in `lib/.github/workflows/`:

| Workflow | When | What |
|---|---|---|
| `ci.yml` | push and pull request | pytest on Python 3.11 to 3.14, mypy on 3.11 and 3.14, build, `twine check --strict`, and a check that the wheel holds `py.typed`. |
| `publish.yml` | tag `v*` | Checks that the tag equals the version in `pyproject.toml`, builds and checks. Runs the same pytest and mypy jobs as `ci.yml` on the tagged commit. Publishes to PyPI with trusted publishing, only if all of them pass. No token. |

- `lib/` is a submodule, and `actions/checkout` does not fetch it. The jobs `library` and `quality` and the workflow `e2e.yml` check out `Paol0B/sannce-aio` into `lib/` at the commit `git rev-parse HEAD:lib` prints.
- Home Assistant installs `sannce-aio` from PyPI, at the version `requirements` in `custom_components/sannce/manifest.json` pins, and so does the bench. The unit tests and mypy use `lib/` instead. A test fails when the pin differs from the version in `lib/pyproject.toml`.
- Every job runs on `ubuntu-24.04` and has a timeout. `ubuntu-latest` moves to Ubuntu 26 on 2026-10-19, so move the runner on purpose, after a test run.
- Every action is pinned to a full commit SHA, with its version in a comment. Update them by hand.
- `hacs/action` runs the image `ghcr.io/hacs/action:main`. Its latest release is from 2022, and the image tag floats.
- GitHub lets you start `ci.yml` or `e2e.yml` by hand only after the file is on master: `gh workflow run e2e.yml`.
- The same checks run on your machine: `scripts/quality.sh`, `scripts/bench.sh hassfest` and `scripts/bench.sh test`. See [Development](../README.md#development).

## Publish the library

PyPI accepts uploads of `sannce-aio` only from the workflow `publish.yml` of `Paol0B/sannce-aio`, in its environment `pypi` (trusted publishing).

A release is a tag pushed in `sannce-aio`. For each release:

1. In `lib/`, on master, set `version` in `pyproject.toml`, commit it and push it to `sannce-aio`. Wait for its CI to pass.
2. Tag that commit and push the tag. `publish.yml` checks that the tag equals the version, then publishes.

   ```sh
   git -C lib tag vX.Y.Z
   git -C lib push origin vX.Y.Z
   ```

3. Watch the run in `Paol0B/sannce-aio` and check the project on PyPI.
4. In this repository, set `requirements` in `custom_components/sannce/manifest.json` to `["sannce-aio==X.Y.Z"]`, `git add lib` and commit both.

A version on PyPI cannot be replaced: fix a bad release with a new version.
