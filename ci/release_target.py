"""Resolve the version, tag and source commit for a Windows build."""

import os
import re
import subprocess
from pathlib import Path


def version_number(value: str) -> str:
    version = value.strip().removeprefix("v")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[.-][0-9A-Za-z.-]+)?", version):
        raise ValueError(f"Invalid version {value!r}. Enter a complete version such as 1.1.0.")
    return version


def tagged_target(version: str, refs: dict[str, str], head_sha: str) -> tuple[str, str]:
    """Keep the existing release tag and build the exact commit it identifies."""
    for tag in (f"v{version}", version):
        ref = f"refs/tags/{tag}"
        if ref in refs:
            return tag, refs.get(f"{ref}^{{}}", refs[ref])
    return f"v{version}", head_sha


def find_tag_refs(version: str) -> dict[str, str]:
    tags = (f"refs/tags/v{version}", f"refs/tags/{version}")
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "origin", *tags, *(f"{tag}^{{}}" for tag in tags)],
        check=True,
        capture_output=True,
        text=True,
    )
    return {ref: sha for sha, ref in (line.split() for line in result.stdout.splitlines())}


def main() -> None:
    event = os.environ["GITHUB_EVENT_NAME"]
    ref = os.environ["GITHUB_REF"]
    commit = os.environ["GITHUB_SHA"]
    tag = ""
    if event == "push":
        tag = ref.removeprefix("refs/tags/")
        version = version_number(tag)
    elif event == "workflow_dispatch":
        version = version_number(os.environ.get("MANUAL_VERSION", ""))
        if os.environ.get("PUBLISH_RELEASE") == "true":
            if ref != "refs/heads/main":
                raise ValueError("Select main in Run workflow to publish a release.")
            if version == "0.0.0":
                raise ValueError("Version 0.0.0 is reserved for preview builds.")
            tag, commit = tagged_target(version, find_tag_refs(version), commit)
    else:
        version = "0.0.0"

    with Path(os.environ["GITHUB_ENV"]).open("a", encoding="utf-8") as env:
        env.write(f"APP_VERSION={version}\n")
    with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
        output.write(f"version={version}\ntag={tag}\ncommit={commit}\n")
    print(f"Building {version} from {commit}" + (f" for Release {tag}." if tag else "."))


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
