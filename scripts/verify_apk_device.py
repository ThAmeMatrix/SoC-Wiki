"""Install and exercise the signed APK on the project's isolated Android emulator."""
from pathlib import Path
import json
import subprocess
import time
from build_apk import ROOT, SDK

ADB=SDK/'platform-tools/adb.exe'
SERIAL='emulator-5556'
OUT=ROOT/'test-results'


def adb(*arguments,timeout=60,check=True,binary=False):
    result=subprocess.run([str(ADB),'-s',SERIAL,*arguments],capture_output=True,text=not binary,encoding=None if binary else 'utf8',errors=None if binary else 'replace',timeout=timeout)
    if check and result.returncode:raise RuntimeError(str(result.stdout)+str(result.stderr))
    return result


def main():
    started=time.monotonic();last=0
    while time.monotonic()-started<480:
        result=adb('shell','getprop','sys.boot_completed',timeout=12,check=False)
        if result.stdout.strip()=='1':break
        elapsed=int(time.monotonic()-started)
        if elapsed-last>=30:print('Waiting for Android startup: '+str(elapsed)+'s',flush=True);last=elapsed
        time.sleep(3)
    else:raise SystemExit('Android did not finish booting within 8 minutes; APK package checks are available separately.')
    print('Android booted; installing the signed offline release.',flush=True)
    for key in ('window_animation_scale','transition_animation_scale','animator_duration_scale'):
        adb('shell','settings','put','global',key,'0')
    adb('shell','cmd','connectivity','airplane-mode','enable')
    assert adb('shell','settings','get','global','airplane_mode_on').stdout.strip()=='1'
    adb('shell','input','keyevent','82')
    app=ROOT/'release/SoCwiki-offline-1.18.0.apk'
    test=ROOT/'android/app/build/outputs/apk/androidTest/release/app-release-androidTest.apk'
    print(adb('install','-r','--no-streaming',str(app),timeout=240).stdout,flush=True)
    print(adb('install','-r','-t',str(test),timeout=120).stdout,flush=True)
    adb('shell','pm','clear','com.socwiki.offline')
    adb('logcat','-c')
    print('Running release WebView regression checks in airplane mode.',flush=True)
    result=adb('shell','am','instrument','-w','com.socwiki.offline.test/com.socwiki.offline.OfflineSmokeTest',timeout=480,check=False)
    output=result.stdout+result.stderr
    (OUT/'android-device-test.txt').write_text(output,encoding='utf8')
    logs=adb('logcat','-d','-s','SoCwiki:E','AndroidRuntime:E',check=False).stdout
    (OUT/'android-device-log.txt').write_text(logs,encoding='utf8')
    screenshot=adb('exec-out','screencap','-p',binary=True,timeout=30).stdout
    (OUT/'android-device.png').write_bytes(screenshot)
    success='INSTRUMENTATION_RESULT: result=passed' in output
    report={'status':'passed' if success else 'failed','serial':SERIAL,'android':adb('shell','getprop','ro.build.version.release').stdout.strip(),
            'airplaneMode':True,'signedReleaseInstalled':True,'output':output,'runtimeErrors':logs,'screenshot':str(OUT/'android-device.png')}
    (OUT/'android-device-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(output,flush=True)
    if not success:raise SystemExit(1)


if __name__=='__main__':main()
