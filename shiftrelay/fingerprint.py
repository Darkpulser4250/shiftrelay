"""Experimental PCM fingerprint matcher. File-based research, not a live app adapter.

Features are centered spectral band energies; matching uses cosine similarity and
offset alignment. Requires NumPy (research.txt). No pretrained model or ad corpus.
"""
import argparse
import json
from pathlib import Path
import wave
import numpy as np

RATE = 8000
HOP = 1024
WINDOW = 2048
BANDS = 24


def read_wav(path):
    with wave.open(str(path), 'rb') as wav:
        if wav.getsampwidth() != 2 or wav.getframerate() != RATE or wav.getnchannels() != 1:
            raise ValueError('Use mono 16-bit PCM WAV at 8000 Hz')
        if wav.getnframes() > RATE * 300:
            raise ValueError('Five minute input limit')
        return np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(float) / 32768


def features(samples):
    if len(samples) < WINDOW + 8 * HOP:
        raise ValueError('At least two seconds of audio required')
    frames = np.lib.stride_tricks.sliding_window_view(samples, WINDOW)[::HOP]
    power = np.abs(np.fft.rfft(frames * np.hanning(WINDOW))) ** 2
    edges = np.unique(np.geomspace(10, WINDOW // 2, BANDS + 1).astype(int))
    energies = np.stack([power[:, lo:hi].mean(axis=1) for lo, hi in zip(edges[:-1], edges[1:])], axis=1)
    # Power compression and centering suppress gain changes and broad noise floors.
    spectral = np.sqrt(energies)
    spectral -= spectral.mean(axis=1, keepdims=True)
    norms = np.linalg.norm(spectral, axis=1, keepdims=True)
    return spectral / np.maximum(norms, 1e-8)


def match(reference, sample):
    if reference.ndim != 2 or sample.ndim != 2 or reference.shape[1] != sample.shape[1]:
        raise ValueError('Incompatible feature shapes')
    if len(sample) > len(reference):
        return {'score': 0.0, 'offset_seconds': None, 'decision': 'unknown'}
    scores = [float(np.mean(np.sum(reference[i:i+len(sample)] * sample, axis=1)))
              for i in range(len(reference) - len(sample) + 1)]
    offset = int(np.argmax(scores))
    return {'score': round(scores[offset], 6), 'offset_seconds': round(offset * HOP / RATE, 3),
            'decision': 'candidate' if scores[offset] >= 0.85 else 'unknown'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('reference', type=Path, help='Known owned/lawfully obtained ad sample')
    parser.add_argument('sample', type=Path, help='A captured audio window, same WAV format')
    args = parser.parse_args()
    result = match(features(read_wav(args.reference)), features(read_wav(args.sample)))
    result['warning'] = 'Experimental similarity score, not a calibrated probability. No device actions performed.'
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
