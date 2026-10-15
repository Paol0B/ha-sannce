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

- `lib/` is a submodule, and `actions/checkout` does not fetch it. The jobs `library`, `quality` and `hassfest` and the workflow `e2e.yml` check out `Paol0B/sannce-aio` into `lib/` at the commit `git rev-parse HEAD:lib` prints. They read it with the deploy key in the Actions secret `SANNCE_AIO_DEPLOY_KEY`. A deploy key opens one repository only, so the checkout of this repository does not use it. Without the secret, the checkout uses the workflow token, which reads `sannce-aio` once it is public.
- Git ignores the library copy in `custom_components/sannce/sannce_aio/`. `scripts/quality.sh` and `scripts/bench.sh` write it from `lib/` with `scripts/vendor-lib.sh` before they use it.
- The `hacs` job ignores four checks that cannot pass yet: `brands` (no logo pull request), `license` (no license), `hacsjson` and `integration_manifest` (HACS reads both files without a token, so a private repository fails). Meanwhile `tests/components/sannce/test_manifest.py` and hassfest cover `hacs.json` and `manifest.json`. All four ignores go away in `ci.yml` when the repositories are public and licensed. `brands` also needs the logo pull request merged.
- Every job runs on `ubuntu-24.04` and has a timeout. `ubuntu-latest` moves to Ubuntu 26 on 2026-10-19, so move the runner on purpose, after a test run.
- Every action is pinned to a full commit SHA, with its version in a comment. Update them by hand.
- `hacs/action` runs the image `ghcr.io/hacs/action:main`. Its latest release is from 2022, and the image tag floats.
- GitHub lets you start `ci.yml` or `e2e.yml` by hand only after the file is on master: `gh workflow run e2e.yml`.
- The same checks run on your machine: `scripts/quality.sh`, `scripts/bench.sh hassfest` and `scripts/bench.sh test`. See [Development](../README.md#development).

## Publish the library

Once, before the first release, on pypi.org: Your account, Publishing, add a pending publisher with these exact values.

| Field | Value |
|---|---|
| PyPI project name | `sannce-aio` |
| Owner | `Paol0B` |
| Repository | `sannce-aio` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

The GitHub environment `pypi` already exists in `Paol0B/sannce-aio`.

A release is a tag pushed in `sannce-aio`. For each release:

1. In `lib/`, on master, set `version` in `pyproject.toml`, commit it and push it to `sannce-aio`. Wait for its CI to pass.
2. Tag that commit and push the tag. `publish.yml` checks that the tag equals the version, then publishes.

   ```sh
   git -C lib tag vX.Y.Z
   git -C lib push origin vX.Y.Z
   ```

3. Watch the run in `Paol0B/sannce-aio` and check the project on PyPI.
4. In this repository, `git add lib` and commit the new pointer.

A version on PyPI cannot be replaced: fix a bad release with a new version.

## After the first PyPI release

The integration then installs the library from PyPI instead of carrying a copy. This is the step to a public HACS release: HACS downloads only the files git tracks, and the copy is not one of them.

1. Set `requirements` in `custom_components/sannce/manifest.json` to `["sannce-aio==X.Y.Z"]`.
2. Delete `scripts/vendor-lib.sh`, the copy in `custom_components/sannce/sannce_aio/` and its line in `.gitignore`. Remove the `vendor-lib.sh` calls from `scripts/bench.sh`, `scripts/deploy.sh` and `scripts/quality.sh`, and the `omit` line in `.coveragerc`. The `hassfest` job in `.github/workflows/ci.yml` then needs no `lib/`: drop its checkout of `sannce-aio`.
3. In `custom_components/sannce/lib.py`, import from `sannce_aio` instead of `.sannce_aio`.
4. Make the bench and the unit tests use the installed library.
   - The bench: Home Assistant installs the library from PyPI when it loads the manifest. The camera image still builds the simulator from `lib/`.
   - The unit tests: `requirements-dev.txt` already installs `lib/`. Change the two tests in `tests/components/sannce/test_manifest.py` that expect no requirements and a vendored copy, and its `VENDORED` constant. `tests/components/sannce/test_siren.py` imports `custom_components.sannce.sannce_aio.connection`: import `sannce_aio.connection` instead.
5. Set `dependency-transparency` to `done` in `custom_components/sannce/quality_scale.yaml` and drop its comment about the vendored library. Remove its line from `publication_only` in `scripts/quality.sh`, so only `brands` stays allowed.
6. In `lib/README.md`, a commit in `sannce-aio`, change Install to `pip install sannce-aio`.
7. Update `README.md`:
   - Install, HACS: HACS can now install the integration.
   - Install, Manual: drop the `scripts/vendor-lib.sh` step.
   - "Container, over SSH": `scripts/deploy.sh` no longer copies the library.
   - Development: drop the copy and the `scripts/vendor-lib.sh` runs.
8. Update `bench/README.md`: the intro names the bundled library, Requirements lists rsync for `scripts/vendor-lib.sh`, and Commands says `up` and `hassfest` copy the library into the integration. The camera image still builds from `lib/`.
9. Run `scripts/quality.sh` and `scripts/bench.sh test`.

## Open decisions

- **License.** Neither repository has one. Pick one before anything goes public.
- **Public repositories.** HACS's default list needs a public repository. The `dependency-transparency` rule needs the library source to be public, with tagged releases built by CI. Both repositories are private now.
- **Brands.** Home Assistant shows the integration's logo from `home-assistant/brands`. That needs a pull request there with a logo for the domain `sannce`. Until it is merged, the HACS `brands` check and the quality scale rule `brands` stay failing, and CI ignores them.
