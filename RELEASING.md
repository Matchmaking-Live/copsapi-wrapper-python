# Releasing

Releases are published to PyPI by GitHub Actions with PyPI Trusted Publishing, so no API token is needed.

1. Update the version in both `pyproject.toml` and `src/copsapi/_core.py` (`VERSION`), and add an entry to `CHANGELOG.md`.
2. Commit and push to `main`, and wait for CI to pass.
3. Tag the commit and push the tag:

   ```sh
   git tag v1.2.0
   git push origin v1.2.0
   ```

The `Release` workflow then checks that the tag matches both version numbers, runs the tests, type check and build, and uploads the package to PyPI. If any step fails, nothing is published.

## One-time setup

On PyPI, open the `copsapi-wrapper` project, go to **Publishing**, and add a GitHub trusted publisher:

| Field | Value |
| --- | --- |
| Owner | `Matchmaking-Live` |
| Repository name | `copsapi-wrapper-python` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |
