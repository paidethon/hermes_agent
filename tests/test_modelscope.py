"""Offline tests for the ModelScope release/keepalive logic (network mocked)."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relpath)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


api = load('modelscope_api', 'scripts/modelscope_api.py')
keepalive = load('modelscope_keepalive', 'scripts/modelscope_keepalive.py')
release = load('modelscope_release', 'scripts/modelscope_release.py')


class SpaceDockerfileParsing(unittest.TestCase):
    def test_digest_extracted_from_various_response_shapes(self):
        digest = 'a' * 64
        for body in (
                f'FROM ghcr.io/x/y@sha256:{digest}\nEXPOSE 7860\n',           # raw text
                json.dumps({'Content': f'FROM ghcr.io/x/y@sha256:{digest}\nEXPOSE 7860\n'}),
                json.dumps({'data': {'content': f'FROM ghcr.io/x/y@sha256:{digest}\n'}}),
                json.dumps({'Data': {'Content': f'FROM ghcr.io/x/y@sha256:{digest}\n'}}),
        ):
            with patch.object(api, 'request_raw', return_value=body), \
                    patch.dict(os.environ, {'SPACE_ID': 'owner/name',
                                            'MODELSCOPE_TOKEN': 'ms-not-real'}):
                self.assertEqual(api.space_dockerfile_digest(), digest)

    def test_unpinned_dockerfile_returns_none(self):
        with patch.object(api, 'request_raw', return_value='FROM ubuntu:24.04\n'), \
                patch.dict(os.environ, {'SPACE_ID': 'owner/name',
                                        'MODELSCOPE_TOKEN': 'ms-not-real'}):
            self.assertIsNone(api.space_dockerfile_digest())


class DeploymentArtifactValidation(unittest.TestCase):
    def test_load_deployment_accepts_and_rejects(self):
        with tempfile.TemporaryDirectory() as temp:
            deploy_dir = Path(temp)
            # The CI artifact stores the full RepoDigest form.
            (deploy_dir / 'image-digest.txt').write_text(
                'ghcr.io/paidethon/hermes_agent@sha256:' + 'b' * 64 + '\n')
            (deploy_dir / 'source-commit.txt').write_text('c' * 40 + '\n')
            digest, commit = release.load_deployment(str(deploy_dir))
            self.assertEqual(digest, 'b' * 64)
            self.assertEqual(commit, 'c' * 40)
            (deploy_dir / 'image-digest.txt').write_text('not-a-digest\n')
            with self.assertRaises(SystemExit):
                release.load_deployment(str(deploy_dir))


class KeepaliveBlindSpot(unittest.TestCase):
    """Connection-level probe failures are a vantage problem, never a
    recovery trigger (2026-09-15: blind redeploy every tick killed sessions)."""

    def run_readiness(self, statuses, space='Running'):
        calls = {'n': 0}
        with patch.object(keepalive.ms, 'space_status', return_value=space), \
                patch.object(keepalive.ms, 'readyz_status',
                             side_effect=lambda: statuses[min(calls.__setitem__('n', calls['n'] + 1) or calls['n'] - 1, len(statuses) - 1)]), \
                patch.object(keepalive.time, 'sleep'):
            return keepalive.readiness_failing()

    def test_runner_blindness_never_triggers_recovery(self):
        self.assertFalse(self.run_readiness([0, 0, 0]))
        self.assertFalse(self.run_readiness([0, 0, 0, 0, 0]))

    def test_reachable_but_not_ready_triggers_recovery(self):
        self.assertTrue(self.run_readiness([503, 503, 503]))

    def test_reachable_and_ready_is_healthy(self):
        self.assertFalse(self.run_readiness([200]))

    def test_mixed_blind_and_single_failure_is_not_actionable(self):
        self.assertFalse(self.run_readiness([0, 0, 503]))


class KeepaliveState(unittest.TestCase):
    def test_state_roundtrip_and_corruption_recovery(self):
        with tempfile.TemporaryDirectory() as temp:
            path = str(Path(temp) / 'state.json')
            keepalive.save_state(path, {'recoveries': [1.0, 2.0]})
            self.assertEqual(keepalive.load_state(path), {'recoveries': [1.0, 2.0]})
            Path(path).write_text('{broken')
            self.assertEqual(keepalive.load_state(path), {'recoveries': []})
            self.assertEqual(keepalive.load_state(str(Path(temp) / 'missing.json')),
                             {'recoveries': []})

    def test_token_and_space_guards_fail_closed(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(api.ApiError):
                api.space_status()
            with self.assertRaises(api.ApiError):
                with patch.dict(os.environ, {'MODELSCOPE_TOKEN': 'ms-not-real'}):
                    api.space_status()  # SPACE_ID missing


if __name__ == '__main__':
    unittest.main()
