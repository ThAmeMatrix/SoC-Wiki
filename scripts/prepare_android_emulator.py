"""Prepare an isolated software emulator without changing Windows virtualization settings."""
from pathlib import Path
import subprocess
from build_apk import environment, SDK, TOOLS


def main():
    env=environment();env['ANDROID_AVD_HOME']=str(TOOLS/'avd')
    (TOOLS/'avd').mkdir(exist_ok=True)
    command=SDK/'cmdline-tools/19.0/bin'
    image='system-images;android-35;google_apis;x86_64'
    print('Installing Android 15 emulator image for offline APK validation.',flush=True)
    with (TOOLS/'emulator-install.log').open('w',encoding='utf8') as log:
        result=subprocess.run([str(command/'sdkmanager.bat'),'--sdk_root='+str(SDK),'emulator',image],env=env,input='y\n'*100,text=True,stdout=log,stderr=subprocess.STDOUT)
    if result.returncode:raise SystemExit((TOOLS/'emulator-install.log').read_text(encoding='utf8')[-5000:])
    if not (TOOLS/'avd/socwiki-test.ini').exists():
        subprocess.run([str(command/'avdmanager.bat'),'create','avd','-n','socwiki-test','-k',image,'-d','pixel_6','-p',str(TOOLS/'avd/socwiki-test.avd')],env=env,input='no\n',text=True,check=True)
    config=TOOLS/'avd/socwiki-test.avd/config.ini'
    data=config.read_text(encoding='utf8')
    settings={'hw.ramSize':'4096','disk.dataPartition.size':'6G','hw.gpu.enabled':'yes','hw.gpu.mode':'swiftshader_indirect','showDeviceFrame':'no'}
    lines=[line for line in data.splitlines() if line.partition('=')[0].strip() not in settings]
    config.write_text('\n'.join(lines+[key+'='+value for key,value in settings.items()])+'\n',encoding='utf8')
    print('Emulator ready.',flush=True)


if __name__=='__main__':main()
