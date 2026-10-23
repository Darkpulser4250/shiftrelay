#!/usr/bin/env python3
"""Build the dependency-free probe with official Android SDK tools and JDK 17+."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'artifacts/shiftrelay-probe.apk')
    args = parser.parse_args()
    sdk = Path(os.environ.get('ANDROID_HOME', os.environ.get('ANDROID_SDK_ROOT', '/nonexistent')))
    tools, android = sdk / 'build-tools/36.0.0', sdk / 'platforms/android-36/android.jar'
    if not android.is_file() or not (tools / 'aapt2').is_file():
        parser.error('Install Android SDK platforms;android-36 and build-tools;36.0.0; set ANDROID_HOME')
    for tool in ('javac', 'keytool'):
        if not shutil.which(tool):
            parser.error('Install JDK 17+ and put javac/keytool on PATH')
    source = ROOT / 'android/probe'
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='shiftrelay-apk-') as temporary:
        work = Path(temporary)
        compiled, classes, dex = work / 'resources.zip', work / 'classes', work / 'dex'
        classes.mkdir(); dex.mkdir()
        run(tools / 'aapt2', 'compile', '--dir', source / 'res', '-o', compiled)
        unsigned = work / 'unsigned.apk'
        run(tools / 'aapt2', 'link', '-o', unsigned, '--manifest', source / 'AndroidManifest.xml',
            '-I', android, compiled)
        run('javac', '-source', '8', '-target', '8', '-classpath', android, '-d', classes,
            *sorted((source / 'src').rglob('*.java')))
        run(tools / 'd8', '--lib', android, '--min-api', '28', '--output', dex, *sorted(classes.rglob('*.class')))
        with zipfile.ZipFile(unsigned, 'a', compression=zipfile.ZIP_DEFLATED) as apk:
            apk.write(dex / 'classes.dex', 'classes.dex')
        aligned = work / 'aligned.apk'
        run(tools / 'zipalign', '-p', '4', unsigned, aligned)
        # Disposable lab signing identity, never a release key. CI publishes APK only.
        key = work / 'lab.keystore'
        run('keytool', '-genkeypair', '-keystore', key, '-storepass', 'android', '-keypass', 'android',
            '-alias', 'lab', '-keyalg', 'RSA', '-keysize', '2048', '-validity', '365',
            '-dname', 'CN=ShiftRelay Disposable Lab Build', '-noprompt')
        run(tools / 'apksigner', 'sign', '--ks', key, '--ks-pass', 'pass:android', '--ks-key-alias', 'lab',
            '--out', args.out, aligned)
        run(tools / 'apksigner', 'verify', '--verbose', args.out)
        run(tools / 'aapt2', 'dump', 'badging', args.out)
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    args.out.with_suffix('.apk.sha256').write_text(digest + '  ' + args.out.name + '\n')
    print('Built:', args.out)


if __name__ == '__main__':
    main()
