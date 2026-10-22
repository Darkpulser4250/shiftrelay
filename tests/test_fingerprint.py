import unittest
try:
    import numpy as np
    from shiftrelay.fingerprint import RATE, features, match
except ImportError:
    np = None


@unittest.skipIf(np is None, 'Install research.txt for fingerprint experiments')
class FingerprintTests(unittest.TestCase):
    def test_offset_gain_and_noise(self):
        rng = np.random.default_rng(27)
        t = np.arange(RATE * 12) / RATE
        # Synthetic changing spectrum, not real ad data.
        envelope = np.repeat(rng.uniform(.1, 1, 24), RATE // 2)
        reference = envelope * (np.sin(2*np.pi*(200*t + 80*t*t)) + .3*np.sin(2*np.pi*670*t))
        sample = reference[RATE*3:RATE*7] * .6 + rng.normal(0, .004, RATE*4)
        result = match(features(reference), features(sample))
        self.assertEqual(result['decision'], 'candidate')
        self.assertLess(abs(result['offset_seconds'] - 3), .2)
        unrelated = rng.normal(0, .1, RATE*4)
        self.assertEqual(match(features(reference), features(unrelated))['decision'], 'unknown')


if __name__ == '__main__':
    unittest.main()
