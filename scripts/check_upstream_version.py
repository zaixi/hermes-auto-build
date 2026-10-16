"""Select a stable upstream image without mixing legacy date and release versions."""
import json
import os
import re
import urllib.request
from urllib.error import HTTPError


UPSTREAM_IMAGE = os.environ['UPSTREAM_IMAGE']
IMAGE_NAME = os.environ['IMAGE_NAME']
FORCE = os.environ.get('FORCE_MODE', 'false').lower() == 'true'
# The oldest release whose image records the dependency selection this build
# consumes: upstream added `pm.build_env --record-selection` in v0.21.7, so
# v0.21.6-style images ship no selection and a sealed rebuild of them would
# silently drop upstream's own extras. They are not valid bases and are never
# backfilled. Legacy date-versioned images keep their uv install path.
BACKFILL_MIN_RELEASE = os.environ.get('BACKFILL_MIN_RELEASE', 'v0.21.7')


def docker_hub_get(path, allow_missing=False):
    request = urllib.request.Request(
        f'https://hub.docker.com/v2{path}', headers={'Accept': 'application/json'}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except HTTPError as exc:
        if allow_missing and exc.code == 404:
            return None
        raise


def version_key(name):
    if not re.fullmatch(r'v\d+\.\d+\.\d+', name):
        return None
    version = tuple(int(part) for part in name[1:].split('.'))
    if version[0] >= 2000:
        # Legacy CalVer images precede the switch to release-version tags.
        return (0, *version) if version >= (2026, 4, 30) else None
    return (1, *version)


print(f'Checking upstream: {UPSTREAM_IMAGE}', flush=True)
path = f'/repositories/{UPSTREAM_IMAGE}/tags?page_size=200'
all_tags = set()
seen_pages = set()
while path:
    if path in seen_pages:
        raise RuntimeError('Docker Hub returned a pagination loop')
    seen_pages.add(path)
    page = docker_hub_get(path)
    if page is None:
        raise RuntimeError('Missing upstream tag listing')
    all_tags.update(tag['name'] for tag in page['results'])
    next_url = page.get('next')
    if next_url and not next_url.startswith('https://hub.docker.com/v2/repositories/' + UPSTREAM_IMAGE + '/tags?'):
        raise RuntimeError('Unexpected Docker Hub pagination URL')
    path = next_url.removeprefix('https://hub.docker.com/v2') if next_url else None
ranked_tags = [(key, name) for name in all_tags if (key := version_key(name)) is not None]
tags = [name for _, name in sorted(ranked_tags, reverse=True)]
if not tags:
    raise RuntimeError('No supported stable upstream tags found; refusing an unknown base')
print(f'  Found {len(tags)} stable tags; newest: {tags[0]}', flush=True)

floor = version_key(BACKFILL_MIN_RELEASE)
if floor is None or floor[0] != 1:
    raise RuntimeError(f'Invalid backfill floor {BACKFILL_MIN_RELEASE!r}')
def eligible_base(tag, release_floor):
    """Date-versioned images keep the uv path; releases must carry a selection."""
    key = version_key(tag)
    if key is None:
        return False
    return key[0] == 0 or key >= release_floor


eligible = [tag for tag in tags if eligible_base(tag, floor)]
if not eligible:
    raise RuntimeError(
        f'No supported stable upstream tags at or above {BACKFILL_MIN_RELEASE}; refusing an unknown base'
    )
if len(eligible) != len(tags):
    print(f'  {len(tags) - len(eligible)} tag(s) below the supported base floor '
          f'{BACKFILL_MIN_RELEASE} excluded', flush=True)

if FORCE:
    if tags[0] not in eligible:
        raise RuntimeError(f'Newest upstream tag {tags[0]} is below the supported base floor '
                           f'{BACKFILL_MIN_RELEASE}')
    selected = tags[0]
else:
    selected = ''
    for tag in eligible:
        if docker_hub_get(f'/repositories/{IMAGE_NAME}/tags/{tag}', allow_missing=True) is None:
            selected = tag
            break
        print(f'  Already built: {tag}', flush=True)

outputs = {
    'should_build': str(bool(selected)).lower(),
    'upstream_tag': selected,
    'is_newest': str(bool(selected) and selected == tags[0]).lower(),
}
print(f'  Decision: {outputs}', flush=True)
with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
    for key, value in outputs.items():
        output.write(f'{key}={value}\n')
