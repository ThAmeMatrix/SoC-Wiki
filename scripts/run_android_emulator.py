"""Keep the headless test emulator attached to the build tool session."""
import subprocess
from build_apk import environment, SDK, TOOLS, ROOT

env=environment()
env['ANDROID_AVD_HOME']=str(TOOLS/'avd')
command=[str(SDK/'emulator/emulator.exe'),'-avd','socwiki-test','-port','5556','-no-window','-no-audio',
         '-no-boot-anim','-accel','off','-gpu','swiftshader','-feature','-Vulkan','-no-snapshot','-cores','1','-memory','2048']
with (ROOT/'test-results/android-emulator.log').open('wb') as output:
    result=subprocess.run(command,env=env,stdout=output,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
print('Emulator exited:',result.returncode,flush=True)
raise SystemExit(result.returncode)
