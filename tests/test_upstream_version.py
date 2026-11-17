"""Exercise the real detector, replacing only Docker Hub HTTP responses."""
from email.message import Message
import io
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/check_upstream_version.py'


class VersionDetectionTests(unittest.TestCase):
    def detect(self, tags, built=(), force=False, upstream_error=None, second_page=(), target_error=None):
        self.target_requests = []

        def urlopen(request, timeout=15):
            url = request.full_url
            if '/repositories/nousresearch/hermes-agent/tags?' in url:
                if upstream_error:
                    raise upstream_error
                page_tags = second_page if 'page=2' in url else tags
                next_url = ('https://hub.docker.com/v2/repositories/nousresearch/hermes-agent/tags?page=2'
                            if second_page and 'page=2' not in url else None)
                return io.BytesIO(json.dumps({'results': [{'name': t} for t in page_tags], 'next': next_url}).encode())
            self.target_requests.append(url.rsplit('/', 1)[-1])
            if target_error:
                raise HTTPError(url, target_error, 'Target API failure', Message(), io.BytesIO())
            name = url.rsplit('/', 1)[-1]
            if name in built:
                return io.BytesIO(b'{"name":"exists"}')
            raise HTTPError(url, 404, 'Not Found', Message(), io.BytesIO())

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            output.touch()
            env = {'UPSTREAM_IMAGE': 'nousresearch/hermes-agent', 'IMAGE_NAME': 'liyujiang/hermes-agent',
                   'FORCE_MODE': str(force).lower(), 'GITHUB_OUTPUT': str(output)}
            with patch.dict(os.environ, env), patch('urllib.request.urlopen', side_effect=urlopen):
                try:
                    runpy.run_path(str(SCRIPT), run_name='__main__')
                except BaseException:
                    # A failed API/selection must never authorize a build or a skip.
                    self.assertEqual(output.read_text(), '')
                    raise
            return dict(line.split('=', 1) for line in output.read_text().splitlines())

    def test_semver_release_wins_over_legacy_date_tags(self):
        self.assertEqual(self.detect(['v2026.9.24', 'v0.23.2', 'v0.23.3']),
                         {'should_build': 'true', 'upstream_tag': 'v0.23.3', 'is_newest': 'true'})

    def test_numeric_semver_sort(self):
        self.assertEqual(self.detect(['v0.9.9', 'v0.23.9', 'v0.23.10'])['upstream_tag'], 'v0.23.10')

    def test_prerelease_branch_and_malformed_tags_excluded(self):
        self.assertEqual(self.detect(['main', 'latest', 'v0.24.0-rc1', 'v0.24.0.1', 'v0.23.2'])['upstream_tag'], 'v0.23.2')

    def test_variant_suffixed_tags_of_the_same_release_are_excluded(self):
        # Docker Hub publishes `vX.Y.Z-desktop` next to `vX.Y.Z`; only the plain tag is a base.
        self.assertEqual(self.detect(['v0.23.2-desktop', 'v0.23.2'])['upstream_tag'], 'v0.23.2')
        self.assertEqual(self.detect(['v0.23.2-desktop', 'v0.23.2'])['is_newest'], 'true')
        with self.assertRaises(RuntimeError):
            self.detect(['v0.23.2-desktop'], force=True)

    def test_built_newest_skips_without_probing_missing_history(self):
        self.assertEqual(self.detect(['v0.23.3', 'v0.23.2', 'v2026.9.24'], built=['v0.23.3']),
                         {'should_build': 'false', 'upstream_tag': '', 'is_newest': 'false'})
        self.assertEqual(self.target_requests, ['v0.23.3'])

    def test_only_newest_is_probed_when_missing(self):
        self.assertEqual(self.detect(['v0.23.3', 'v0.23.2'])['upstream_tag'], 'v0.23.3')
        self.assertEqual(self.target_requests, ['v0.23.3'])

    def test_force_rebuilds_newest_not_missing_older_tag(self):
        self.assertEqual(self.detect(['v0.23.3', 'v0.23.2'], built=['v0.23.3'], force=True),
                         {'should_build': 'true', 'upstream_tag': 'v0.23.3', 'is_newest': 'true'})
        self.assertEqual(self.target_requests, [])

    def test_force_when_all_built(self):
        self.assertEqual(self.detect(['v0.23.2'], built=['v0.23.2'], force=True)['upstream_tag'], 'v0.23.2')

    def test_all_built_writes_all_skip_outputs(self):
        self.assertEqual(self.detect(['v0.23.2'], built=['v0.23.2']),
                         {'should_build': 'false', 'upstream_tag': '', 'is_newest': 'false'})

    def test_empty_or_unsupported_tags_fail_closed_even_when_forced(self):
        for tags in ([], ['latest', 'v0.23.0-rc1', 'v2026.4.29']):
            with self.subTest(tags=tags), self.assertRaises(RuntimeError):
                self.detect(tags, force=True)

    def test_upstream_error_is_not_successful_skip_even_when_forced(self):
        for force in (False, True):
            with self.subTest(force=force), self.assertRaises(TimeoutError):
                self.detect([], force=force, upstream_error=TimeoutError('network timeout'))

    def test_target_rate_limit_and_server_errors_are_not_missing_tags(self):
        for code in (401, 429, 500):
            with self.subTest(code=code), self.assertRaises(HTTPError):
                self.detect(['v0.23.2'], target_error=code)

    def test_minimum_release_and_calver_exclusion_even_when_forced(self):
        for tags in (['v0.23.1'], ['v0.22.9', 'v2026.9.24'], ['v2026.5.29']):
            for force in (False, True):
                with self.subTest(tags=tags, force=force), self.assertRaises(RuntimeError):
                    self.detect(tags, force=force)
        self.assertEqual(self.detect(['v0.23.1', 'v0.23.2'])['upstream_tag'], 'v0.23.2')

    def test_noncanonical_semver_is_not_an_official_stable_tag(self):
        self.assertEqual(self.detect(['v00.99.0', 'v0.023.9', 'v0.23.099',
                                      'v0.24.0+build', '0.24.0', 'v0.23.2'])['upstream_tag'], 'v0.23.2')

    def test_legacy_floor_override_cannot_reenable_old_builds(self):
        with patch.dict(os.environ, {'BACKFILL_MIN_RELEASE': 'v0.21.7'}):
            with self.assertRaises(RuntimeError):
                self.detect(['v0.22.1'], force=True)

    def test_follows_pagination(self):
        self.assertEqual(self.detect(['v2026.9.24'], second_page=['v0.23.2'])['upstream_tag'], 'v0.23.2')


if __name__ == '__main__':
    unittest.main()
