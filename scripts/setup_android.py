"""Install a project-local Android build toolchain from verified official archives."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import shutil
import subprocess
import zipfile
import requests
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/'.tools'
SDK=TOOLS/'android-sdk'
GRADLE_VERSION='8.13'
GRADLE_SHA256='20f1b1176237254a6fc204d8434196fa11a4cfb387567519c61556e8710aed78'


def download(url, destination, digest, algorithm='sha256'):
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():
        with destination.open('rb') as f:
            if hashlib.file_digest(f,algorithm).hexdigest()==digest:return
    part=destination.with_suffix('.partial')
    print('Downloading '+url,flush=True)
    with requests.get(url,stream=True,timeout=(20,120)) as response:
        response.raise_for_status()
        h=hashlib.new(algorithm)
        with part.open('wb') as f:
            for block in response.iter_content(1024*1024):
                f.write(block);h.update(block)
    if h.hexdigest()!=digest:raise RuntimeError('Checksum mismatch: '+url)
    part.replace(destination)
    print('Verified '+destination.name,flush=True)


def unzip(source,destination):
    destination.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        for name in archive.namelist():
            if not (destination/name).resolve().is_relative_to(destination.resolve()):
                raise RuntimeError('Invalid ZIP path')
        archive.extractall(destination)


def sdk_package(name):
    response=requests.get('https://dl.google.com/android/repository/repository2-3.xml',timeout=40)
    response.raise_for_status()
    tree=ET.fromstring(response.content)
    for package in tree:
        if package.attrib.get('path')!=name:continue
        for archive in package.findall('./archives/archive'):
            if archive.findtext('host-os')=='windows':
                item=archive.find('complete');checksum=item.find('checksum')
                return ('https://dl.google.com/android/repository/'+item.findtext('url'),checksum.text,checksum.attrib.get('type','sha1'))
    raise RuntimeError('SDK package not found: '+name)


def main():
    SDK.mkdir(parents=True,exist_ok=True)
    cmd=SDK/'cmdline-tools'/'19.0'/'bin'/'sdkmanager.bat'
    gradle=TOOLS/('gradle-'+GRADLE_VERSION)/'bin'/'gradle.bat'
    def command_line():
        if cmd.exists():return
        url,checksum,algorithm=sdk_package('cmdline-tools;19.0')
        file=TOOLS/'downloads'/url.rsplit('/',1)[-1]
        download(url,file,checksum,algorithm)
        staging=TOOLS/'sdk-unpack'
        unzip(file,staging)
        (SDK/'cmdline-tools').mkdir(exist_ok=True)
        shutil.move(str(staging/'cmdline-tools'),str(SDK/'cmdline-tools'/'19.0'))
    def gradle_dist():
        if gradle.exists():return
        file=TOOLS/'downloads'/f'gradle-{GRADLE_VERSION}-bin.zip'
        download('https://downloads.gradle.org/distributions/'+file.name,file,GRADLE_SHA256)
        unzip(file,TOOLS)
    with ThreadPoolExecutor(2) as pool:
        for future in [pool.submit(command_line),pool.submit(gradle_dist)]:future.result()
    env=os.environ.copy()
    env['ANDROID_SDK_ROOT']=str(SDK)
    env['GRADLE_USER_HOME']=str(TOOLS/'gradle-cache')
    print('Installing SDK platform 36, build tools and adb',flush=True)
    packages=['platforms;android-36','build-tools;36.0.0','platform-tools']
    log=TOOLS/'sdk-install.log'
    with log.open('w',encoding='utf8') as f:
        result=subprocess.run([str(cmd),'--sdk_root='+str(SDK),*packages],input='y\n'*100,text=True,stdout=f,stderr=subprocess.STDOUT,env=env)
    if result.returncode:
        print(log.read_text(encoding='utf8')[-6000:]);raise SystemExit(result.returncode)
    (ROOT/'android').mkdir(exist_ok=True)
    (ROOT/'android'/'local.properties').write_text('sdk.dir='+SDK.as_posix().replace(':','\\:')+'\n',encoding='utf8')
    print('Android build tools ready: '+str(SDK),flush=True)


if __name__=='__main__':main()
