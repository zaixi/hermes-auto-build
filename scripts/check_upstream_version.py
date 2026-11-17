"""Build only the latest supported official stable release; never backfill history."""
import json
import os
import re
import urllib.request
from urllib.error import HTTPError


UPSTREAM_IMAGE = os.environ['UPSTREAM_IMAGE']
IMAGE_NAME = os.environ['IMAGE_NAME']
FORCE = os.environ.get('FORCE_MODE', 'false').lower() == 'true'
MIN_RELEASE = (0, 23, 2)


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
    """Accept canonical v-prefixed SemVer stable tags, not legacy CalVer."""
    if not re.fullmatch(r'v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', name):
        return None
    version = tuple(int(part) for part in name[1:].split('.'))
    if version[0] >= 2000 or version < MIN_RELEASE:
        return None
    return version


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
if not ranked_tags:
    raise RuntimeError('No supported stable upstream tags at or above v0.23.2; refusing an unknown base')
newest = max(ranked_tags)[1]
print(f'  Found {len(ranked_tags)} supported stable tags; newest: {newest}', flush=True)

if FORCE:
    selected = newest
else:
    selected = newest if docker_hub_get(
        f'/repositories/{IMAGE_NAME}/tags/{newest}', allow_missing=True
    ) is None else ''
    if not selected:
        print(f'  Already built: {newest}; no historical backfill', flush=True)

outputs = {
    'should_build': str(bool(selected)).lower(),
    'upstream_tag': selected,
    'is_newest': str(bool(selected)).lower(),
}
print(f'  Decision: {outputs}', flush=True)
with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
    for key, value in outputs.items():
        output.write(f'{key}={value}\n')
