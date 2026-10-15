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
        def urlopen(request, timeout=15):
            url = request.full_url
            if '/repositories/nousresearch/hermes-agent/tags?' in url:
                if upstream_error:
                    raise upstream_error
                page_tags = second_page if 'page=2' in url else tags
                next_url = ('https://hub.docker.com/v2/repositories/nousresearch/hermes-agent/tags?page=2'
                            if second_page and 'page=2' not in url else None)
                return io.BytesIO(json.dumps({'results': [{'name': t} for t in page_tags], 'next': next_url}).encode())
            if target_error:
                raise HTTPError(url, target_error, 'Target API failure', Message(), None)
            name = url.rsplit('/', 1)[-1]
            if name in built:
                return io.BytesIO(b'{"name":"exists"}')
            raise HTTPError(url, 404, 'Not Found', Message(), None)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'output'
            output.touch()
            env = {'UPSTREAM_IMAGE': 'nousresearch/hermes-agent', 'IMAGE_NAME': 'liyujiang/hermes-agent',
                   'FORCE_MODE': str(force).lower(), 'GITHUB_OUTPUT': str(output)}
            with patch.dict(os.environ, env), patch('urllib.request.urlopen', side_effect=urlopen):
                try:
                    runpy.run_path(str(SCRIPT), run_name='__main__')
                except SystemExit as exc:
                    if exc.code not in (None, 0):
                        raise
            return dict(line.split('=', 1) for line in output.read_text().splitlines())

    def test_semver_release_wins_over_legacy_date_tags(self):
        self.assertEqual(self.detect(['v2026.9.24', 'v0.22.0', 'v0.22.1']),
                         {'should_build': 'true', 'upstream_tag': 'v0.22.1', 'is_newest': 'true'})
    def test_numeric_semver_sort(self):
        self.assertEqual(self.detect(['v0.9.9', 'v0.22.1', 'v0.22.10'])['upstream_tag'], 'v0.22.10')

    def test_legacy_numeric_sort_and_minimum(self):
        self.assertEqual(self.detect(['v2026.5.7', 'v2026.5.29', 'v2026.4.29'])['upstream_tag'], 'v2026.5.29')

    def test_prerelease_branch_and_malformed_tags_excluded(self):
        self.assertEqual(self.detect(['main', 'latest', 'v0.23.0-rc1', 'v0.23.0.1', 'v0.22.1'])['upstream_tag'], 'v0.22.1')

    def test_gap_fill_does_not_push_latest(self):
        self.assertEqual(self.detect(['v0.22.1', 'v0.22.0'], built=['v0.22.1']),
                         {'should_build': 'true', 'upstream_tag': 'v0.22.0', 'is_newest': 'false'})

    def test_force_rebuilds_newest_not_missing_older_tag(self):
        self.assertEqual(self.detect(['v0.22.1', 'v0.22.0'], built=['v0.22.1'], force=True)['upstream_tag'], 'v0.22.1')

    def test_force_when_all_built(self):
        self.assertEqual(self.detect(['v0.22.1'], built=['v0.22.1'], force=True)['upstream_tag'], 'v0.22.1')

    def test_all_built_writes_all_skip_outputs(self):
        self.assertEqual(self.detect(['v0.22.1'], built=['v0.22.1']),
                         {'should_build': 'false', 'upstream_tag': '', 'is_newest': 'false'})

    def test_empty_or_unsupported_tags_fail_closed_even_when_forced(self):
        for tags in ([], ['latest', 'v0.23.0-rc1', 'v2026.4.29']):
            with self.subTest(tags=tags), self.assertRaises(RuntimeError):
                self.detect(tags, force=True)

    def test_upstream_error_is_not_successful_skip(self):
        with self.assertRaises(TimeoutError):
            self.detect([], upstream_error=TimeoutError('network timeout'))

    def test_target_rate_limit_and_server_errors_are_not_missing_tags(self):
        for code in (401, 429, 500):
            with self.subTest(code=code), self.assertRaises(HTTPError):
                self.detect(['v0.22.1'], target_error=code)

    def test_follows_pagination(self):
        self.assertEqual(self.detect(['v2026.9.24'], second_page=['v0.22.1'])['upstream_tag'], 'v0.22.1')


if __name__ == '__main__':
    unittest.main()
