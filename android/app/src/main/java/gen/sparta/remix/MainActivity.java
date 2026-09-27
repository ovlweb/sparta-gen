package gen.sparta.remix;

import android.Manifest;
import android.annotation.SuppressLint;
import android.annotation.TargetApi;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.Insets;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.util.Log;
import android.view.View;
import android.view.WindowInsets;
import android.webkit.ConsoleMessage;
import android.webkit.JavascriptInterface;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/** The app: Sparta Gen's web app (served by the engine on 127.0.0.1) in a full-screen WebView. */
public class MainActivity extends Activity {
    private static final int REQ_FILE = 1;
    private static final int REQ_PERMISSIONS = 2;
    private static final String BG = "#0e0909";

    private final Handler ui = new Handler(Looper.getMainLooper());
    private FrameLayout root;
    private WebView web;
    private ValueCallback<Uri[]> fileCallback;
    private boolean appLoaded = false;
    private boolean resumed = false;
    private boolean reloadOnResume = false;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        root = new FrameLayout(this);
        root.setBackgroundColor(0xff0e0909);
        setContentView(root);
        // Android 15 draws apps under the system bars: keep the page clear of them (and of the keyboard).
        root.setOnApplyWindowInsetsListener((View v, WindowInsets insets) -> {
            if (Build.VERSION.SDK_INT >= 30) {
                Insets i = insets.getInsets(WindowInsets.Type.systemBars() | WindowInsets.Type.ime());
                v.setPadding(i.left, i.top, i.right, i.bottom);
            }
            return insets;
        });
        web = newWebView();

        showMessage(getString(R.string.starting));
        askPermissions();
        startEngine();
        handleShared(getIntent());
    }

    /** The page's WebView, in the window. */
    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    private WebView newWebView() {
        WebView page = new WebView(this);
        page.setBackgroundColor(0xff0e0909);
        root.addView(page, new FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT));

        WebSettings s = page.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setAllowContentAccess(true);
        page.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if ("127.0.0.1".equals(u.getHost())) {
                    return false;                                // the app itself
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, u));  // links out: the browser
                } catch (ActivityNotFoundException ignored) {
                    // nothing to open it with
                }
                return true;
            }

            @TargetApi(26)
            @Override
            public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
                pageGone(view, detail.didCrash());
                return true;
            }
        });
        page.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
                if (fileCallback != null) {
                    fileCallback.onReceiveValue(null);
                }
                fileCallback = callback;
                Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
                pick.addCategory(Intent.CATEGORY_OPENABLE);
                pick.setType("*/*");
                String[] types = mimeTypes(params.getAcceptTypes());
                if (types.length > 0) {
                    pick.putExtra(Intent.EXTRA_MIME_TYPES, types);
                }
                try {
                    startActivityForResult(Intent.createChooser(pick, getString(R.string.pick_file)), REQ_FILE);
                    return true;
                } catch (ActivityNotFoundException e) {
                    fileCallback = null;
                    return false;
                }
            }

            @Override
            public boolean onConsoleMessage(ConsoleMessage m) {
                Log.d(EngineService.TAG, "page: " + m.message() + " (" + m.sourceId() + ":" + m.lineNumber() + ")");
                return true;
            }
        });
        // Renders, audio and sample packs: saved to the phone's Movies / Music / Download folders.
        page.setDownloadListener((url, agent, disposition, mime, length) -> Saver.save(this, url, disposition, mime));
        page.addJavascriptInterface(new Bridge(), "SpartaAndroid");
        return page;
    }

    /**
     * The page's own process is gone: Android ended it to reclaim memory (often while the app is in the
     * background), or it crashed.  The engine — and a render it is making — lives on in this process, so only
     * the page is made again; left unhandled, Android would end the whole app with it.
     */
    private void pageGone(WebView dead, boolean crashed) {
        if (dead != web || isDestroyed()) {
            return;                                             // a page already replaced, or the app is closing
        }
        Log.w(EngineService.TAG, "page process gone (" + (crashed ? "crashed" : "ended by the system")
                + "): the page is made again");
        root.removeView(dead);
        dead.destroy();
        fileCallback = null;                                    // a file picker opened by that page: pick again
        web = newWebView();
        if (resumed) {
            reloadPage();
        } else {
            reloadOnResume = true;                              // in the background: when the app is back in front
        }
    }

    private void reloadPage() {
        if (EngineService.port() > 0) {
            appLoaded = true;
            web.loadUrl("http://127.0.0.1:" + EngineService.port() + "/");
        } else {
            showMessage(getString(R.string.starting));
            startEngine();
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        handleShared(intent);
    }

    @Override
    protected void onResume() {
        super.onResume();
        resumed = true;
        if (reloadOnResume) {
            reloadOnResume = false;
            reloadPage();
        } else if (appLoaded && EngineService.port() == 0) {      // the system stopped the engine: bring it back
            appLoaded = false;
            showMessage(getString(R.string.starting));
            startEngine();
        }
    }

    @Override
    protected void onPause() {
        resumed = false;
        super.onPause();
    }

    private void startEngine() {
        Intent svc = new Intent(this, EngineService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(svc);
        } else {
            startService(svc);
        }
        new Thread(() -> {
            long until = System.currentTimeMillis() + 180_000;   // the first start unpacks Python
            while (EngineService.port() == 0 && EngineService.error() == null
                    && System.currentTimeMillis() < until) {
                sleep(150);
            }
            int port = EngineService.port();
            ui.post(() -> {
                if (port > 0) {
                    appLoaded = true;
                    web.loadUrl("http://127.0.0.1:" + port + "/");
                } else {
                    String why = EngineService.error();
                    showMessage(getString(R.string.engine_failed) + "<pre>" + escape(why == null ? "timeout" : why) + "</pre>");
                }
            });
        }, "spartagen-wait").start();
    }

    private void showMessage(String html) {
        String page = "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head>"
                + "<body style='background:" + BG + ";color:#f3e9e6;font-family:sans-serif;display:flex;"
                + "align-items:center;justify-content:center;height:90vh;text-align:center;padding:16px'>"
                + "<div><h2 style='color:#e7b62c;letter-spacing:.12em'>SPARTA<span style='color:#ff3a4f'>GEN</span></h2>"
                + "<p>" + html + "</p></div></body></html>";
        web.loadDataWithBaseURL(null, page, "text/html", "utf-8", null);
    }

    /** A video shared to the app ("Share → Sparta Gen" in the gallery): make it the source. */
    private void handleShared(Intent intent) {
        if (intent == null) {
            return;
        }
        Uri uri = null;
        if (Intent.ACTION_SEND.equals(intent.getAction())) {
            uri = Build.VERSION.SDK_INT >= 33 ? intent.getParcelableExtra(Intent.EXTRA_STREAM, Uri.class)
                    : intent.getParcelableExtra(Intent.EXTRA_STREAM);
        } else if (Intent.ACTION_VIEW.equals(intent.getAction())) {
            uri = intent.getData();
        }
        if (uri == null) {
            return;
        }
        final Uri source = uri;
        Toast.makeText(this, R.string.loading_shared, Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            try {
                File dir = new File(getExternalFilesDir(null) != null ? getExternalFilesDir(null) : getFilesDir(),
                        "SpartaGen/shared");
                if (!dir.isDirectory() && !dir.mkdirs()) {
                    throw new java.io.IOException("cannot create " + dir);
                }
                File file = new File(dir, displayName(source));
                try (InputStream in = getContentResolver().openInputStream(source);
                     OutputStream out = new FileOutputStream(file)) {
                    Saver.pipe(in, out);
                }
                long until = System.currentTimeMillis() + 180_000;
                while (EngineService.port() == 0 && System.currentTimeMillis() < until) {
                    sleep(200);
                }
                post("/api/source/path", "{\"path\": " + jsonString(file.getAbsolutePath()) + "}");
                ui.post(() -> {
                    if (EngineService.port() > 0) {
                        appLoaded = true;
                        web.loadUrl("http://127.0.0.1:" + EngineService.port() + "/");
                    }
                });
            } catch (Exception e) {
                Log.e(EngineService.TAG, "shared file", e);
                ui.post(() -> Toast.makeText(this, getString(R.string.shared_failed, String.valueOf(e.getMessage())),
                        Toast.LENGTH_LONG).show());
            }
        }, "spartagen-shared").start();
    }

    private String displayName(Uri uri) {
        String name = null;
        try (Cursor c = getContentResolver().query(uri, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                name = c.getString(0);
            }
        } catch (Exception ignored) {
            // not a content uri with a name
        }
        if (name == null || name.trim().isEmpty()) {
            name = uri.getLastPathSegment() != null ? uri.getLastPathSegment() : "shared.mp4";
        }
        return name.replaceAll("[^\\w.\\- ()\\[\\]]", "_");
    }

    private static void post(String path, String json) throws java.io.IOException {
        HttpURLConnection c = (HttpURLConnection) new URL("http://127.0.0.1:" + EngineService.port() + path).openConnection();
        try {
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setRequestProperty("Content-Type", "application/json");
            byte[] body = json.getBytes(StandardCharsets.UTF_8);
            c.setFixedLengthStreamingMode(body.length);
            try (OutputStream out = c.getOutputStream()) {
                out.write(body);
            }
            if (c.getResponseCode() >= 400) {
                throw new java.io.IOException("engine answered " + c.getResponseCode());
            }
        } finally {
            c.disconnect();
        }
    }

    @Override
    protected void onActivityResult(int request, int result, Intent data) {
        if (request == REQ_FILE) {
            if (fileCallback != null) {
                fileCallback.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
                fileCallback = null;
            }
            return;
        }
        super.onActivityResult(request, result, data);
    }

    @SuppressWarnings("deprecation")
    @Override
    public void onBackPressed() {
        moveTaskToBack(true);        // the app has one page: Back leaves it running (renders go on)
    }

    private void askPermissions() {
        List<String> want = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= 33) {
            want.add(Manifest.permission.POST_NOTIFICATIONS);        // the "engine running" notification
        }
        if (Build.VERSION.SDK_INT <= 28) {
            want.add(Manifest.permission.WRITE_EXTERNAL_STORAGE);    // saving to Movies/Music/Download
        }
        List<String> missing = new ArrayList<>();
        for (String p : want) {
            if (checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED) {
                missing.add(p);
            }
        }
        if (!missing.isEmpty()) {
            requestPermissions(missing.toArray(new String[0]), REQ_PERMISSIONS);
        }
    }

    /** The page's accept="video/*,audio/*" as MIME types for the system picker. */
    private static String[] mimeTypes(String[] accept) {
        List<String> out = new ArrayList<>();
        if (accept != null) {
            for (String a : accept) {
                for (String t : a.split(",")) {
                    t = t.trim();
                    if (t.contains("/")) {
                        out.add(t);
                    }
                }
            }
        }
        return out.toArray(new String[0]);
    }

    private static String escape(String s) {
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }

    private static String jsonString(String s) {
        return "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\"";
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }

    /** window.SpartaAndroid in the page. */
    private class Bridge {
        @JavascriptInterface
        public void quit() {
            ui.post(() -> {
                stopService(new Intent(MainActivity.this, EngineService.class));
                finishAndRemoveTask();
            });
        }
    }
}
