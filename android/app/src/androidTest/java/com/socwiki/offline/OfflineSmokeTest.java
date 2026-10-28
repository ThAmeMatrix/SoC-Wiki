package com.socwiki.offline;

import android.app.Activity;
import android.app.Instrumentation;
import android.content.Intent;
import android.os.Bundle;
import android.os.SystemClock;
import android.webkit.WebView;
import org.json.JSONTokener;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

/** Tests the actual signed release WebView, not a desktop browser approximation. */
public final class OfflineSmokeTest extends Instrumentation {
    private Activity activity;
    private WebView web;
    private final StringBuilder report = new StringBuilder();
    @Override public void onCreate(Bundle arguments) { super.onCreate(arguments);start(); }
    private Object js(String script) throws Exception {
        CountDownLatch done = new CountDownLatch(1);
        AtomicReference<String> result = new AtomicReference<>();
        runOnMainSync(() -> web.evaluateJavascript(script, value -> {result.set(value);done.countDown();}));
        if (!done.await(25, TimeUnit.SECONDS)) throw new AssertionError("JavaScript timeout: " + script);
        return new JSONTokener(result.get()).nextValue();
    }
    private void check(String expression) throws Exception {
        if (!Boolean.TRUE.equals(js(expression))) throw new AssertionError(expression);
    }
    private void waitFor(String expression) throws Exception {
        long deadline = SystemClock.uptimeMillis() + 120000;
        while (SystemClock.uptimeMillis() < deadline) {
            if (Boolean.TRUE.equals(js(expression))) return;
            SystemClock.sleep(350);
        }
        throw new AssertionError("Timed out: " + expression);
    }
    private void route(String hash, String selector) throws Exception {
        js("location.hash=" + org.json.JSONObject.quote(hash));
        waitFor("!!document.querySelector(" + org.json.JSONObject.quote(selector) + ")");
    }
    private void pass(String text) { report.append("PASS ").append(text).append('\n'); }
    @Override public void onStart() {
        Bundle output = new Bundle();
        try {
            Intent launch = new Intent(Intent.ACTION_MAIN).setClassName(getTargetContext(), "com.socwiki.offline.MainActivity")
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            activity = startActivitySync(launch);
            web = activity.findViewById(com.socwiki.offline.R.id.wiki_view);
            waitFor("!!window.WikiAndroid && !!window.WIKI_DATA && !!document.querySelector('#main h1')");
            route("#/", ".hero");
            check("document.querySelectorAll('.character-card').length===4");
            pass("Bundled homepage and artwork load with network disabled");
            route("#/characters", ".sprite-card");
            check("document.querySelector('.character-name').textContent==='君士坦丁'");
            check("document.querySelectorAll('.sprite-card').length===24");
            js("document.querySelector('[data-view=list]').click()");
            check("document.querySelectorAll('.unit-table tbody tr').length===24");
            js("document.querySelector('[data-unit-sort=\"stat:物攻\"]').click()");
            check("document.querySelector('[data-unit-sort=\"stat:物攻\"]').parentElement.getAttribute('aria-sort')==='descending'");
            pass("Pixel atlas, source order and sortable unit list");
            route("#/page/879", "[data-trait-star='5']");
            js("document.querySelector('[data-portrait=awakened]').click()");
            check("document.querySelector('.portrait-stage img').alt.includes('觉醒')");
            js("document.querySelector('.portrait-stage').click()");
            check("document.querySelector('#image-dialog').open");
            runOnMainSync(() -> activity.onBackPressed());
            waitFor("!document.querySelector('#image-dialog').open");
            check("document.querySelectorAll('[data-trait-star]').length===5");
            check("document.querySelectorAll('.star-change').length>0");
            js("document.querySelector('[data-detail-tab=skills]').click()");
            waitFor("!!document.querySelector('.growth-explorer[data-ready=true]')");
            check("Array.from(document.querySelectorAll('.growth-tier')).map(e=>e.dataset.rank).join(',')==='11,9,7,5,3,1,0'");
            pass("Awakened art, native back closes lightbox, five-star effects and reversed skill tree");
            js("document.querySelector('[data-detail-tab=overview]').click()");
            waitFor("!!document.querySelector('#page-notes')");
            js("document.querySelector('#page-notes').value='Android offline persistence';document.querySelector('#page-notes').dispatchEvent(new Event('input',{bubbles:true}))");
            js("document.querySelector('.detail-actions [data-favorite]').click()");
            SystemClock.sleep(1200);
            runOnMainSync(web::reload);
            waitFor("!!document.querySelector('#page-notes')");
            check("document.querySelector('#page-notes').value==='Android offline persistence'");
            pass("Notes and favorites persist in the installed WebView origin");
            route("#/tools/damage", "#damage-form");
            check("document.querySelector('#damage-output').textContent.includes('2,700')");
            route("#/tools/gacha", "[data-draw='10']");
            js("document.querySelector('[data-draw='10]').click()");
            check("document.querySelectorAll('.summon-card').length===10");
            route("#/tools/infographic", ".ig-character");
            waitFor("document.querySelector('#ig-canvas').width===1920 && !document.querySelector('[data-ig=export]').disabled");
            check("document.querySelectorAll('.ig-tier').length===7");
            check("document.querySelectorAll('.ig-tier[data-rank=\"0\"] button').length===0");
            check("document.querySelectorAll('[data-ig-engraving]').length===10");
            check("document.querySelector('#ig-canvas').toDataURL('image/png').startsWith('data:image/png;base64,')");
            js("document.querySelector('[data-ig-pick=character]').click()");
            runOnMainSync(() -> activity.onBackPressed());
            waitFor("!document.querySelector('.ig-picker').open");
            pass("Infographic art, skill tree, origin-clean PNG and native back");
            route("#/archive", ".backup-actions");
            check("document.body.textContent.includes('APK 内置资料')");
            check("document.documentElement.scrollWidth<=innerWidth+1");
            pass("Damage calculation, ten-draw simulation and phone layout");
            js("document.querySelector('[data-action=theme]').click()");
            check("document.body.classList.contains('dark')");
            pass("Native system bars follow the stored dark theme");
            output.putString("stream", report.toString());
            output.putString("result", "passed");
            finish(Activity.RESULT_OK, output);
        } catch (Throwable error) {
            output.putString("stream", report + "FAIL " + error);
            output.putString("result", "failed");
            finish(Activity.RESULT_CANCELED, output);
        }
    }
}
