"""Offline contracts for the build workflow (stdlib only, no runner dependencies)."""
from pathlib import Path
import re
import unittest

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/build.yml'


class BuildWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text()
        jobs = self.workflow.split('\njobs:\n', 1)[1]
        self.jobs = dict(re.findall(r'^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)', jobs,
                                    flags=re.MULTILINE | re.DOTALL))

    def test_version_tests_remain_before_detection(self):
        check = self.jobs['check']
        self.assertLess(check.index('test_upstream_version.py'),
                        check.index('run: python3 scripts/check_upstream_version.py'))

    def test_build_tests_only_run_after_should_build(self):
        check, build = self.jobs['check'], self.jobs['build']
        self.assertIn("if: needs.check.outputs.should_build == 'true'", build)
        for filename in ('test_image_dependencies.py', 'test_image_tools.py', 'test_sealed_drift_gate.py',
                         'test_build_workflow.py'):
            with self.subTest(filename=filename):
                self.assertNotIn(filename, check)
                self.assertIn(filename, build)
                self.assertLess(build.index(filename), build.index('uses: docker/setup-buildx-action@'))

    def test_one_unconditional_build_publishes_both_tags_after_build(self):
        build = self.jobs['build']
        self.assertEqual(build.count('uses: docker/build-push-action@'), 1)
        self.assertNotIn('is_newest', build)
        self.assertNotIn('gap fill', build.lower())
        step = re.search(r'      - name: [^\n]+\n(?:(?!      - name:).)*uses: docker/build-push-action@[^\n]+\n(?:(?!      - name:).)*',
                         build, re.DOTALL)
        assert step is not None
        self.assertNotRegex(step.group(0), r'\n        if:')
        self.assertIn('push: true', step.group(0))
        self.assertIn('BASE_TAG=${{ needs.check.outputs.upstream_tag }}', step.group(0))
        self.assertIn('${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:latest', step.group(0))
        self.assertIn('${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ needs.check.outputs.upstream_tag }}',
                      step.group(0))
        # build-push-action exports/pushes only after a successful BuildKit build;
        # prohibit a separate pre-build retag or manifest publication.
        self.assertNotRegex(build, r'docker (?:push|manifest)|imagetools create')

    def test_workflow_serializes_pushes_without_cancelling_running_builds(self):
        header = self.workflow.split('\njobs:\n', 1)[0]
        block = re.search(r'^concurrency:\n((?:  [^\n]*\n)+)', header, re.MULTILINE)
        assert block is not None, 'workflow must declare a top-level concurrency group'
        self.assertIn('group: ${{ github.workflow }}', block.group(1))
        self.assertIn('cancel-in-progress: false', block.group(1))
        self.assertNotIn('github.ref', block.group(1))


if __name__ == '__main__':
    unittest.main()
