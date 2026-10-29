package com.socwiki.offline;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.util.Base64;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.webkit.ConsoleMessage;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;
import android.window.OnBackInvokedDispatcher;

import androidx.webkit.WebViewAssetLoader;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicBoolean;

/** A local-only reader. External websites are delegated to the user's browser. */
public final class MainActivity extends Activity {
    static final String ORIGIN = "https://appassets.androidplatform.net";
    static final String HOME_URL = ORIGIN + "/assets/wiki/index.html";
    private static final int PICK_FILE = 4101, SAVE_FILE = 4102;
    private static final int MAX_EXPORT_BYTES = 64 * 1024 * 1024;
    private final ExecutorService files = Executors.newSingleThreadExecutor();
    private final AtomicBoolean exporting = new AtomicBoolean();
    private WebView browser;
    private FrameLayout root;
    private TextView loading;
    private ValueCallback<Uri[]> filePicker;
    private File pendingExport;
    private boolean backPending;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        root = new FrameLayout(this);
        root.setBackgroundColor(Color.rgb(247, 248, 242));
        setContentView(root);
        configureInsets();
        try {
            browser = new WebView(this);
        } catch (RuntimeException error) {
            showFatal("无法启动系统网页组件，请先安装或更新 Android System WebView。", false);
            return;
        }
        browser.setId(R.id.wiki_view);
        browser.setBackgroundColor(Color.rgb(247, 248, 242));
        root.addView(browser, new FrameLayout.LayoutParams(-1, -1));
        loading = new TextView(this);
        loading.setText("铃兰档案馆\n\n正在打开本地资料…");
        loading.setTextColor(Color.rgb(68, 91, 58));
        loading.setTextSize(18);
        loading.setGravity(Gravity.CENTER);
        loading.setBackgroundColor(Color.rgb(247, 248, 242));
        root.addView(loading, new FrameLayout.LayoutParams(-1, -1));

        WebSettings settings = browser.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setAllowFileAccess(false);
        settings.setAllowContentAccess(true); // User-selected documents only, through the system picker.
        settings.setAllowFileAccessFromFileURLs(false);
        settings.setAllowUniversalAccessFromFileURLs(false);
        settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        settings.setMediaPlaybackRequiresUserGesture(true);
        settings.setGeolocationEnabled(false);
        settings.setBuiltInZoomControls(true);
        settings.setDisplayZoomControls(false);
        settings.setUseWideViewPort(true);
        settings.setLoadWithOverviewMode(true);
        settings.setTextZoom(100);
        settings.setSupportMultipleWindows(false);
        CookieManager.getInstance().setAcceptCookie(false);
        CookieManager.getInstance().setAcceptThirdPartyCookies(browser, false);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        browser.addJavascriptInterface(new LocalBridge(), "AndroidOffline");

        WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this)).build();
        browser.setWebViewClient(new WebViewClient() {
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (localOrigin(uri) && uri.getPath() != null && uri.getPath().startsWith("/assets/wiki/")) {
                    WebResourceResponse result = loader.shouldInterceptRequest(uri);
                    if (result != null) return result;
                }
                if ("GET".equals(request.getMethod()) && "https".equals(uri.getScheme())
                        && uri.getUserInfo() == null && (uri.getPort() == -1 || uri.getPort() == 443)
                        && (("wiki.biligame.com".equals(uri.getHost()) && "/llzj/api.php".equals(uri.getPath()))
                        || ("patchwiki.biligame.com".equals(uri.getHost()) && uri.getPath() != null && uri.getPath().startsWith("/images/llzj/")))) return null;
                return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found",
                        Collections.singletonMap("Cache-Control", "no-store"),
                        new ByteArrayInputStream("Local archive only".getBytes(StandardCharsets.UTF_8)));
            }
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri uri = request.getUrl();
                if (trustedDocument(uri)) return false;
                if (request.isForMainFrame() && !localOrigin(uri)) external(uri.toString());
                return true;
            }
            @Override public void doUpdateVisitedHistory(WebView view, String url, boolean reload) {
                remember(url);
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (trustedDocument(Uri.parse(url))) {
                    loading.setVisibility(View.GONE);
                    remember(url);
                }
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (request.isForMainFrame()) showFatal("本地资料打开失败，请重新打开。", true);
            }
        });
        browser.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (filePicker != null) filePicker.onReceiveValue(null);
                filePicker = callback;
                Intent intent = new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                        .setType("*/*").putExtra(Intent.EXTRA_MIME_TYPES, new String[]{"application/json", "text/plain", "application/octet-stream"});
                try { startActivityForResult(intent, PICK_FILE); }
                catch (ActivityNotFoundException error) {
                    filePicker.onReceiveValue(null); filePicker = null;
                    notifyUser("系统文件选择器不可用。");
                }
                return true;
            }
            @Override public boolean onConsoleMessage(ConsoleMessage message) {
                if (message.messageLevel() == ConsoleMessage.MessageLevel.ERROR)
                    Log.e("SoCwiki", message.message() + " @ " + message.sourceId() + ":" + message.lineNumber());
                return true;
            }
        });
        if (Build.VERSION.SDK_INT >= 33)
            getOnBackInvokedDispatcher().registerOnBackInvokedCallback(OnBackInvokedDispatcher.PRIORITY_DEFAULT, this::goBack);
        String last = getPreferences(MODE_PRIVATE).getString("lastUrl", HOME_URL);
        if (!trustedDocument(Uri.parse(last))) last = HOME_URL;
        if (state == null || browser.restoreState(state) == null) browser.loadUrl(last);
    }

    private void configureInsets() {
        if (Build.VERSION.SDK_INT >= 30) getWindow().setDecorFitsSystemWindows(false);
        else getWindow().getDecorView().setSystemUiVisibility(View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
        root.setOnApplyWindowInsetsListener((view, insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets safe = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
                view.setPadding(safe.left, safe.top, safe.right, safe.bottom);
            } else view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
    }

    private static boolean localOrigin(Uri uri) {
        return "https".equals(uri.getScheme()) && "appassets.androidplatform.net".equals(uri.getHost())
                && (uri.getPort() == -1 || uri.getPort() == 443) && uri.getUserInfo() == null;
    }
    private static boolean trustedDocument(Uri uri) {
        return localOrigin(uri) && "/assets/wiki/index.html".equals(uri.getPath());
    }
    private void remember(String url) {
        if (url != null && trustedDocument(Uri.parse(url))) getPreferences(MODE_PRIVATE).edit().putString("lastUrl", url).apply();
    }
    private void external(String value) {
        Uri uri = Uri.parse(value);
        if (!("https".equals(uri.getScheme()) || "http".equals(uri.getScheme())) || uri.getHost() == null || localOrigin(uri)) return;
        runOnUiThread(() -> {
            try { startActivity(new Intent(Intent.ACTION_VIEW, uri).addCategory(Intent.CATEGORY_BROWSABLE)); }
            catch (ActivityNotFoundException error) { notifyUser("没有可打开链接的浏览器。"); }
        });
    }
    private void setTheme(boolean dark) {
        if (browser == null || isDestroyed()) return;
        int color = dark ? Color.rgb(25, 36, 30) : Color.rgb(247, 248, 242);
        root.setBackgroundColor(color);
        browser.setBackgroundColor(color);
        getWindow().setStatusBarColor(color);
        getWindow().setNavigationBarColor(color);
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController controller = getWindow().getInsetsController();
            if (controller != null) {
                int flags = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                controller.setSystemBarsAppearance(dark ? 0 : flags, flags);
            }
        } else {
            int flags = View.SYSTEM_UI_FLAG_LAYOUT_STABLE | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN;
            if (!dark) flags |= View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            getWindow().getDecorView().setSystemUiVisibility(flags);
        }
    }
    private void showFatal(String message, boolean retry) {
        if (loading != null) loading.setVisibility(View.GONE);
        AlertDialog.Builder dialog = new AlertDialog.Builder(this).setTitle("铃兰档案馆").setMessage(message)
                .setNegativeButton("关闭", (d, which) -> finish());
        if (retry) dialog.setPositiveButton("重新打开", (d, which) -> browser.loadUrl(HOME_URL));
        dialog.setCancelable(false).show();
    }
    private void notifyUser(String message) {
        runOnUiThread(() -> { if (!isFinishing() && !isDestroyed()) Toast.makeText(this, message, Toast.LENGTH_LONG).show(); });
    }
    // Android 13+ uses the OnBackInvokedDispatcher registered in onCreate.
    // This override remains solely for Android 8–12 and the instrumentation test.
    @SuppressLint("GestureBackNavigation")
    @Override public void onBackPressed() { goBack(); }
    private void goBack() {
        if (browser == null) { finish(); return; }
        if (backPending) return;
        backPending = true;
        browser.evaluateJavascript("Boolean(window.WikiAndroid && WikiAndroid.back())", result -> {
            backPending = false;
            if (browser == null || isFinishing() || isDestroyed()) return;
            if ("true".equals(result)) return;
            if (browser.canGoBack()) browser.goBack();
            else if (!browser.getUrl().endsWith("#/") && browser.getUrl().contains("#")) browser.loadUrl(HOME_URL + "#/");
            else finish();
        });
    }

    private static String filename(String name, String mime) {
        String safe = name == null ? "铃兰档案馆" : name.replaceAll("[\\\\/:*?\"<>|\\p{Cntrl}]", "_");
        if (safe.length() > 110) safe = safe.substring(0, 110);
        if (safe.trim().isEmpty()) safe = "铃兰档案馆";
        String suffix = "application/json".equals(mime) ? ".json" : "image/png".equals(mime) ? ".png" : "image/webp".equals(mime) ? ".webp" : "image/jpeg".equals(mime) ? ".jpg" : "";
        if (!suffix.isEmpty() && !safe.toLowerCase(Locale.ROOT).endsWith(suffix)) safe += suffix;
        return safe;
    }
    private void chooseExport(File file, String name, String mime) {
        runOnUiThread(() -> {
            if (isFinishing() || isDestroyed()) { file.delete(); exporting.set(false); return; }
            pendingExport = file;
            Intent intent = new Intent(Intent.ACTION_CREATE_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE)
                    .setType(mime).putExtra(Intent.EXTRA_TITLE, filename(name, mime));
            try { startActivityForResult(intent, SAVE_FILE); }
            catch (ActivityNotFoundException error) {
                file.delete();pendingExport = null;exporting.set(false);notifyUser("系统文件保存器不可用。");
            }
        });
    }
    public final class LocalBridge {
        @JavascriptInterface public void setDarkTheme(boolean dark) { runOnUiThread(() -> setTheme(dark)); }
        @JavascriptInterface public void openExternal(String url) { if (url != null && url.length() < 8192) external(url); }
        @JavascriptInterface public void saveBase64(String name, String mime, String data) {
            if (data == null || data.length() > MAX_EXPORT_BYTES * 4 / 3 + 8
                    || !("application/json".equals(mime) || "image/png".equals(mime))) {
                notifyUser("导出内容无效或过大。"); return;
            }
            if (!exporting.compareAndSet(false, true)) { notifyUser("请先完成当前文件的保存。"); return; }
            files.execute(() -> {
                File temporary = null;
                try {
                    byte[] bytes = Base64.decode(data, Base64.DEFAULT);
                    if (bytes.length > MAX_EXPORT_BYTES) throw new IllegalArgumentException("File too large");
                    temporary = File.createTempFile("wiki-export-", ".tmp", getCacheDir());
                    try (OutputStream output = new FileOutputStream(temporary)) { output.write(bytes); }
                    chooseExport(temporary, name, mime);
                } catch (Exception error) {
                    if (temporary != null) temporary.delete();
                    exporting.set(false);notifyUser("准备导出文件失败，请重试。");
                }
            });
        }
        @JavascriptInterface public void saveAsset(String url, String name) {
            Uri uri = Uri.parse(url == null ? "" : url);
            String path = uri.getPath();
            if (!localOrigin(uri) || path == null || !path.matches("/assets/wiki/assets/(wiki|brand)/[A-Za-z0-9._-]+\\.(webp|png|jpg|jpeg)")) {
                notifyUser("无法保存此图片。");return;
            }
            if (!exporting.compareAndSet(false, true)) { notifyUser("请先完成当前文件的保存。"); return; }
            files.execute(() -> {
                File temporary = null;
                try {
                    temporary = File.createTempFile("wiki-export-", ".tmp", getCacheDir());
                    try (InputStream source = getAssets().open(path.substring("/assets/".length())); OutputStream output = new FileOutputStream(temporary)) {
                        byte[] buffer = new byte[65536]; int read;
                        while ((read = source.read(buffer)) != -1) output.write(buffer, 0, read);
                    }
                    String mime = path.endsWith(".webp") ? "image/webp" : path.endsWith(".png") ? "image/png" : "image/jpeg";
                    chooseExport(temporary, name, mime);
                } catch (Exception error) {
                    if (temporary != null) temporary.delete();
                    exporting.set(false);notifyUser("图片保存失败，请重试。");
                }
            });
        }
    }
    @Override protected void onActivityResult(int request, int result, Intent intent) {
        super.onActivityResult(request, result, intent);
        if (request == PICK_FILE && filePicker != null) {
            Uri[] selected = result == RESULT_OK && intent != null && intent.getData() != null ? new Uri[]{intent.getData()} : null;
            filePicker.onReceiveValue(selected);filePicker = null;
        } else if (request == SAVE_FILE) {
            File source = pendingExport; pendingExport = null;
            if (source == null) { exporting.set(false);notifyUser("保存已中断，请重新导出。");return; }
            Uri destination = result == RESULT_OK && intent != null ? intent.getData() : null;
            if (destination == null) { source.delete();exporting.set(false);notifyUser("已取消保存。");return; }
            files.execute(() -> {
                try (InputStream input = new FileInputStream(source); OutputStream output = getContentResolver().openOutputStream(destination, "wt")) {
                    if (output == null) throw new IllegalStateException("No output stream");
                    byte[] buffer = new byte[65536];int read;
                    while ((read = input.read(buffer)) != -1) output.write(buffer, 0, read);
                    notifyUser("已保存到所选位置。");
                } catch (Exception error) { notifyUser("保存失败，请检查目标位置后重试。"); }
                finally { source.delete();exporting.set(false); }
            });
        }
    }
    @Override protected void onSaveInstanceState(Bundle state) {
        if (browser != null) browser.saveState(state);
        super.onSaveInstanceState(state);
    }
    @Override protected void onPause() { if (browser != null) { remember(browser.getUrl());browser.onPause(); } super.onPause(); }
    @Override protected void onResume() { super.onResume();if (browser != null) browser.onResume(); }
    @Override protected void onDestroy() {
        if (filePicker != null) { filePicker.onReceiveValue(null);filePicker = null; }
        if (browser != null) { browser.stopLoading();root.removeView(browser);browser.removeJavascriptInterface("AndroidOffline");browser.destroy();browser = null; }
        files.shutdown();super.onDestroy();
    }
}
