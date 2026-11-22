#!/usr/bin/env bash
# Release VERSION from the current master commit: push, wait for master CI to go green on
# both OSes, then tag, wait for the tag build, and fetch the stable channel as an App does.
# Commit the version bump and its CHANGELOG.md section first.
set -euo pipefail

version="${1:?usage: packaging/release.sh X.Y.Z}"
version="${version#v}"
tag="v$version"
root="$(git rev-parse --show-toplevel)"
cd "$root"

[ "$(git branch --show-current)" = master ] || { echo "release from master" >&2; exit 1; }
sha="$(git rev-parse HEAD)"
git show HEAD:pyproject.toml | grep -qx "version = \"$version\"" \
  || { echo "HEAD pyproject.toml is not version $version" >&2; exit 1; }
git show HEAD:CHANGELOG.md | grep -q "^## \[$version\]" \
  || { echo "HEAD CHANGELOG.md has no ## [$version] section" >&2; exit 1; }
if git rev-parse -q --verify "refs/tags/$tag" >/dev/null || git ls-remote --exit-code --tags origin "$tag" >/dev/null; then
  echo "$tag already exists" >&2; exit 1
fi

watch_run() {  # watch_run REF: wait for the push run of $sha on REF and fail unless it succeeds
  local ref="$1" id=""
  for _ in $(seq 60); do
    id="$(gh run list --commit "$sha" --event push --json databaseId,headBranch \
      --jq "[.[] | select(.headBranch == \"$ref\")][0].databaseId // empty")"
    [ -n "$id" ] && break
    sleep 5
  done
  [ -n "$id" ] || { echo "no CI run for $ref at $sha" >&2; exit 1; }
  echo "watching CI run $id for $ref"
  gh run watch "$id" --exit-status >/dev/null || { gh run view "$id" --json jobs \
    --jq '.jobs[] | "\(.name): \(.conclusion)"' >&2; echo "CI failed for $ref: run $id" >&2; exit 1; }
}

git push origin master
watch_run master
git tag -a "$tag" -m "Midgard Farm $version" "$sha"
git push origin "$tag"
watch_run "$tag"
gh release view "$tag" --json assets --jq '.assets[].name'
"$root/.venv/bin/python" packaging/check_published.py "$version"
echo "released $tag"
