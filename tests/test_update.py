import base64
import json
from pathlib import Path
import unittest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from shiftrelay.policy import load
from shiftrelay.update import approved_update


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.policy = load(Path(__file__).resolve().parents[1] / 'fixtures/policy.demo.json')
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        self.document = {'version': 2, 'expires': 1200, 'block_rules': self.policy['block_rules'],
                         'canaries': [{'host': 'localhost', 'path': '/ads.js', 'method': 'GET', 'expected': 'block'},
                                      {'host': 'localhost', 'path': '/content', 'method': 'GET', 'expected': 'pass'}]}

    def envelope(self):
        payload = json.dumps(self.document).encode()
        return json.dumps({'payload_b64': base64.b64encode(payload).decode(), 'signature_b64': base64.b64encode(self.key.sign(payload)).decode()}).encode()

    def test_valid_rule_update_preserves_scope(self):
        new = approved_update(self.policy, self.envelope(), self.public, now=1000)
        for field in ('mode', 'inspect_hosts', 'bypass_hosts', 'owned_hls_hosts'):
            self.assertEqual(new[field], self.policy[field])

    def test_tamper_rejected(self):
        envelope = json.loads(self.envelope()); envelope['payload_b64'] = base64.b64encode(b'{}').decode()
        with self.assertRaises(InvalidSignature): approved_update(self.policy, json.dumps(envelope).encode(), self.public, now=1000)

    def test_replay_expiry_scope_and_bad_canary_rejected(self):
        for change in [{'version': 1}, {'expires': 500}, {'inspect_hosts': ['netflix.com']},
                       {'block_rules': [{'id': 'bad', 'host': 'netflix.com', 'path': '/'}]},
                       {'canaries': [{'host': 'localhost', 'path': '/content', 'method': 'GET', 'expected': 'block'}]}]:
            previous = self.document.copy(); self.document.update(change)
            with self.assertRaises(ValueError): approved_update(self.policy, self.envelope(), self.public, now=1000)
            self.document = previous


if __name__ == '__main__': unittest.main()
