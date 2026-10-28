# 铃兰档案馆 · Android

这是离线 Wiki 的原生 Android 容器，应用 ID 为 `com.socwiki.offline`。最低 Android 8.0（API 26），目标 Android 16（API 36），无 CPU 架构限制。需使用支持现代网页的 Android System WebView。

APK 内置完整页面、搜索和图片，约 505 MB；不申请联网、相册或存储权限。初次安装后即可离线阅读。图片与备份保存到系统文件选择器中指定的位置，导入使用系统文件选择器。网页中的外部链接交给系统浏览器打开。

返回键优先关闭图片、搜索和侧栏，再返回上一页。收藏、笔记、工具记录保存在应用本地。覆盖安装同签名的新版本会保留记录；卸载应用会清除记录，请先从“资料馆信息”导出个人备份。

## 构建

在项目根目录执行（Python、requests、JDK 17 或 21）：

```powershell
python scripts/setup_android.py
python scripts/build_apk.py
python scripts/verify_android_bridge.py
```

工具安装在项目 `.tools/` 中，不修改全局 Java、Android 或 Gradle 配置。构建自动同步当前离线 Wiki 到 APK，生成 `release/SoCwiki-offline-1.13.3.apk` 及 SHA-256 校验文件，并检查签名、最低版本、联网更新权限和所有内置资源。

首次构建会创建 `android/.signing/release.jks` 和 `release.properties`。这两份私有文件不会进入 APK 或版本控制，必须一起安全保存，以便后续构建可覆盖安装的更新。请勿把它们包含在对外分享的源码或文件包里。升级时递增 `app/build.gradle` 的 `versionCode` 和 `versionName`。

工程使用官方 [WebViewAssetLoader](https://developer.android.com/develop/ui/views/layout/webapps/load-local-content) 加载 APK 中的资源，固定本地 HTTPS 来源，无外部站点内容进入 WebView。应用文件导出通过 Android Storage Access Framework，APK 使用本地发布证书签名，未上传到应用商店。

## 测试

`scripts/verify_android_bridge.py` 验证 JSON 备份、PNG 导出、图片保存、链接跳转、返回逻辑和主题适配；`scripts/build_apk.py` 同时运行 Android Lint 和安装包完整性检查。

`src/androidTest` 的原生测试运行在实际签名发布版本上，覆盖离线首页、像素角色列表、数值排序、觉醒立绘、五星个性、技能树、笔记、工具与系统返回。可安装 `app/build/outputs/apk/androidTest/release/app-release-androidTest.apk` 后执行：

```powershell
adb shell am instrument -w com.socwiki.offline.test/com.socwiki.offline.OfflineSmokeTest
```

测试工程和测试 APK 不需安装在日常阅读设备上。

本次交付的签名检查、全部内置文件比对、Android Lint（0 个错误）及网页与安卓接口测试均通过。当前 Windows 主机的 Android Emulator 在启动系统前以 `0xC0000005` 退出，切换单核与软件渲染后仍失败，因此尚未完成模拟器安装运行或真机验证；不将构建成功表述为设备实测通过。

一图流工坊已经内置：编辑角色、技能搭配、装备塔罗与刻印后，PNG 和方案 JSON 均调用系统保存窗口。工坊按角色保存独立草稿；转移方案请在工坊中导出 JSON。
