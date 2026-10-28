"""Build and verify a signed, self-contained Android APK. Signing stays local."""
from pathlib import Path
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
ANDROID=ROOT/'android'
TOOLS=ROOT/'.tools'
SDK=TOOLS/'android-sdk'


def environment():
    env=os.environ.copy()
    env['ANDROID_SDK_ROOT']=str(SDK)
    env['ANDROID_USER_HOME']=str(TOOLS/'android-user')
    env['GRADLE_USER_HOME']=str(TOOLS/'gradle-cache')
    return env


def signing():
    folder=ANDROID/'.signing'
    folder.mkdir(exist_ok=True)
    properties=folder/'release.properties'
    key=folder/'release.jks'
    if key.exists() and properties.exists():return
    if key.exists() or properties.exists():raise SystemExit('Incomplete signing files; restore the matching key and properties before rebuilding.')
    password=secrets.token_urlsafe(32)
    env=environment();env['SOCWIKI_SIGNING_PASSWORD']=password
    subprocess.run(['keytool','-genkeypair','-keystore',str(key),'-storetype','JKS','-alias','socwiki',
                    '-keyalg','RSA','-keysize','3072','-validity','10000','-dname','CN=SoCwiki Offline, OU=Personal Archive, O=SoCwiki',
                    '-storepass:env','SOCWIKI_SIGNING_PASSWORD','-keypass:env','SOCWIKI_SIGNING_PASSWORD'],env=env,check=True)
    properties.write_text('storePassword='+password+'\nkeyAlias=socwiki\nkeyPassword='+password+'\n',encoding='utf8')
    print('Created local release signing key (excluded from the APK and version control).',flush=True)


def audit_apk(path):
    tools=SDK/'build-tools'/'36.0.0'
    signature=subprocess.run([str(tools/'apksigner.bat'),'verify','--verbose','--print-certs',str(path)],check=True,text=True,capture_output=True).stdout
    assert 'Verified using v2 scheme (APK Signature Scheme v2): true' in signature,signature
    permissions=subprocess.run([str(tools/'aapt.exe'),'dump','permissions',str(path)],check=True,text=True,capture_output=True).stdout
    assert 'android.permission.INTERNET' in permissions,permissions
    manifest=subprocess.run([str(tools/'aapt.exe'),'dump','badging',str(path)],check=True,text=True,capture_output=True,encoding='utf8').stdout
    assert "sdkVersion:'26'" in manifest and "targetSdkVersion:'36'" in manifest,manifest
    assert 'application-debuggable' not in manifest
    generated=ANDROID/'app/build/generated/wikiAssets'
    count=0
    with zipfile.ZipFile(path) as archive:
        assert not archive.testzip()
        assert not any('.signing/' in n or n.endswith(('.jks','.keystore')) or 'data/raw/' in n for n in archive.namelist())
        for file in generated.rglob('*'):
            if not file.is_file():continue
            name='assets/'+file.relative_to(generated).as_posix()
            assert hashlib.sha256(archive.read(name)).digest()==hashlib.sha256(file.read_bytes()).digest(),name
            count+=1
    return {'signature':signature,'permissions':permissions,'manifest':manifest,'bundledFiles':count,'apk':str(path),'bytes':path.stat().st_size}


def main():
    archive=json.loads((ROOT/'data/archive.json').read_text(encoding='utf8'))
    if not archive['complete']:raise SystemExit('Archive is incomplete.')
    if not (SDK/'build-tools/36.0.0/apksigner.bat').exists():
        subprocess.run([sys.executable,str(ROOT/'scripts/setup_android.py')],check=True)
    signing()
    gradle=TOOLS/'gradle-8.13/bin/gradle.bat'
    subprocess.run([str(gradle),'--no-daemon','--console=plain',':app:assembleRelease',':app:assembleReleaseAndroidTest',':app:lintRelease'],cwd=ANDROID,env=environment(),check=True)
    built=ANDROID/'app/build/outputs/apk/release/app-release.apk'
    report=audit_apk(built)
    release=ROOT/'release';release.mkdir(exist_ok=True)
    metadata=json.loads((built.parent/'output-metadata.json').read_text(encoding='utf8'))['elements'][0]
    destination=release/('SoCwiki-offline-'+metadata['versionName']+'.apk')
    shutil.copy2(built,destination)
    with destination.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
    destination.with_suffix('.apk.sha256').write_text(digest+'  '+destination.name+'\n',encoding='utf8')
    report.update(apk=str(destination),sha256=digest,status='passed')
    (ROOT/'test-results').mkdir(exist_ok=True)
    (ROOT/'test-results/android-package-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(f'PASS signed release APK: {destination}\n{destination.stat().st_size/1024/1024:.1f} MiB; {report["bundledFiles"]} bundled files\nSHA256 {digest}',flush=True)


if __name__=='__main__':main()
