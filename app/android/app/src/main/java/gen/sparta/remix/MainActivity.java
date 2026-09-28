package gen.sparta.remix;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.OpenableColumns;
import android.util.Log;

import androidx.annotation.NonNull;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import io.flutter.embedding.android.FlutterActivity;
import io.flutter.embedding.engine.FlutterEngine;
import io.flutter.plugin.common.MethodCall;
import io.flutter.plugin.common.MethodChannel;

/**
 * The Flutter app, plus what only Android can do for it: start the engine service and hand over its port
 * and token ("gen.sparta/engine"), and the system's document picker and "Save as" ("gen.sparta/files").
 */
public class MainActivity extends FlutterActivity {
    private static final int REQ_OPEN = 4101;
    private static final int REQ_SAVE = 4102;
    private static final int REQ_PERMISSIONS = 4103;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private MethodChannel engineChannel;
    private MethodChannel.Result pendingOpen;
    private MethodChannel.Result pendingSave;
    private String saveSource;
    /** A file shared to the app before the Flutter side asked for it. */
    private String sharedPath;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        askPermissions();
        handleShared(getIntent());
    }

    @Override
    protected void onNewIntent(@NonNull Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        handleShared(intent);
    }

    @Override
    public void configureFlutterEngine(@NonNull FlutterEngine flutterEngine) {
        super.configureFlutterEngine(flutterEngine);
        engineChannel = new MethodChannel(flutterEngine.getDartExecutor().getBinaryMessenger(), "gen.sparta/engine");
        engineChannel.setMethodCallHandler(this::onEngineCall);
        new MethodChannel(flutterEngine.getDartExecutor().getBinaryMessenger(), "gen.sparta/files")
                .setMethodCallHandler(this::onFilesCall);
    }

    // ── the engine ──
    private void onEngineCall(@NonNull MethodCall call, @NonNull MethodChannel.Result result) {
        switch (call.method) {
            case "start":
                startEngine(result);
                break;
            case "shared":           // a video shared to the app while it was starting
                result.success(sharedPath);
                sharedPath = null;
                break;
            case "background":       // Back on the first page: leave the app running (a render goes on)
                moveTaskToBack(true);
                result.success(null);
                break;
            default:
                result.notImplemented();
        }
    }

    private void startEngine(MethodChannel.Result result) {
        Intent svc = new Intent(this, EngineService.class);
        try {
            if (Build.VERSION.SDK_INT >= 26) {
                startForegroundService(svc);
            } else {
                startService(svc);
            }
        } catch (RuntimeException e) {               // e.g. not allowed from the background
            result.error("engine", "The engine service could not start: " + e.getMessage(), null);
            return;
        }
        new Thread(() -> {
            long until = System.currentTimeMillis() + 180_000;    // the first start unpacks Python
            while (EngineService.port() == 0 && EngineService.error() == null
                    && System.currentTimeMillis() < until) {
                sleep(150);
            }
            int port = EngineService.port();
            String token = EngineService.token();
            String why = EngineService.error();
            ui.post(() -> {
                if (port > 0) {
                    Map<String, Object> r = new HashMap<>();
                    r.put("port", port);
                    r.put("token", token);
                    result.success(r);
                } else {
                    result.error("engine", why != null ? why : "The engine did not start in time.", null);
                }
            });
        }, "spartagen-wait").start();
    }

    private void askPermissions() {
        // The "engine running" notification (Android 13+); the app works without it.
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_PERMISSIONS);
        }
    }

    // ── files: the system's document picker and "Save as" ──
    private void onFilesCall(@NonNull MethodCall call, @NonNull MethodChannel.Result result) {
        switch (call.method) {
            case "open": {
                if (pendingOpen != null) {
                    pendingOpen.success(null);
                }
                pendingOpen = result;
                List<String> mimes = call.argument("mime");
                Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT)
                        .addCategory(Intent.CATEGORY_OPENABLE)
                        .setType("*/*");
                if (mimes != null && !mimes.isEmpty()) {
                    pick.putExtra(Intent.EXTRA_MIME_TYPES, mimes.toArray(new String[0]));
                }
                try {
                    startActivityForResult(pick, REQ_OPEN);
                } catch (RuntimeException e) {
                    pendingOpen = null;
                    result.error("files", "No app can pick files: " + e.getMessage(), null);
                }
                break;
            }
            case "saveAs": {
                if (pendingSave != null) {
                    pendingSave.success(false);
                }
                pendingSave = result;
                saveSource = call.argument("path");
                String name = call.argument("name");
                String mime = call.argument("mime");
                Intent save = new Intent(Intent.ACTION_CREATE_DOCUMENT)
                        .addCategory(Intent.CATEGORY_OPENABLE)
                        .setType(mime != null ? mime : "application/octet-stream")
                        .putExtra(Intent.EXTRA_TITLE, name);
                try {
                    startActivityForResult(save, REQ_SAVE);
                } catch (RuntimeException e) {
                    pendingSave = null;
                    result.error("files", "No app can save files: " + e.getMessage(), null);
                }
                break;
            }
            default:
                result.notImplemented();
        }
    }

    @Override
    protected void onActivityResult(int request, int code, Intent data) {
        if (request == REQ_OPEN) {
            MethodChannel.Result r = pendingOpen;
            pendingOpen = null;
            Uri uri = code == RESULT_OK && data != null ? data.getData() : null;
            if (r == null) {
                return;
            }
            if (uri == null) {
                r.success(null);
                return;
            }
            new Thread(() -> {
                try {
                    String path = copyIn(uri, "picked");
                    ui.post(() -> r.success(path));
                } catch (Exception e) {
                    Log.e(EngineService.TAG, "open " + uri, e);
                    ui.post(() -> r.error("files", "Could not read that file: " + e.getMessage(), null));
                }
            }, "spartagen-open").start();
            return;
        }
        if (request == REQ_SAVE) {
            MethodChannel.Result r = pendingSave;
            String src = saveSource;
            pendingSave = null;
            saveSource = null;
            Uri uri = code == RESULT_OK && data != null ? data.getData() : null;
            if (r == null) {
                return;
            }
            if (uri == null || src == null) {
                r.success(false);
                return;
            }
            new Thread(() -> {
                try (InputStream in = new FileInputStream(src);
                     OutputStream out = getContentResolver().openOutputStream(uri, "w")) {
                    if (out == null) {
                        throw new IOException("cannot write there");
                    }
                    pipe(in, out);
                    ui.post(() -> r.success(true));
                } catch (Exception e) {
                    Log.e(EngineService.TAG, "save " + uri, e);
                    ui.post(() -> r.error("files", "Could not save it there: " + e.getMessage(), null));
                }
            }, "spartagen-save").start();
            return;
        }
        super.onActivityResult(request, code, data);
    }

    /** A video shared to the app ("Share → Sparta Gen"): copied in, then given to the Flutter side. */
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
        intent.setAction(Intent.ACTION_MAIN);        // handled once (not again after a rotation)
        final Uri source = uri;
        new Thread(() -> {
            try {
                String path = copyIn(source, "shared");
                ui.post(() -> {
                    sharedPath = path;
                    if (engineChannel != null) {
                        engineChannel.invokeMethod("shared", path);
                    }
                });
            } catch (Exception e) {
                Log.e(EngineService.TAG, "shared file", e);
            }
        }, "spartagen-shared").start();
    }

    /** A copy of a picked or shared document where the engine can read it. */
    private String copyIn(Uri uri, String folder) throws IOException {
        File base = getExternalFilesDir(null) != null ? getExternalFilesDir(null) : getFilesDir();
        File dir = new File(base, "SpartaGen/" + folder);
        if (!dir.isDirectory() && !dir.mkdirs()) {
            throw new IOException("cannot create " + dir);
        }
        File file = new File(dir, displayName(uri));
        try (InputStream in = getContentResolver().openInputStream(uri);
             OutputStream out = new FileOutputStream(file)) {
            pipe(in, out);
        }
        return file.getAbsolutePath();
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
            name = uri.getLastPathSegment() != null ? uri.getLastPathSegment() : "file";
        }
        return name.replaceAll("[^\\w.\\- ()\\[\\]]", "_");
    }

    static void pipe(InputStream in, OutputStream out) throws IOException {
        if (in == null) {
            throw new IOException("nothing to read");
        }
        byte[] buf = new byte[1 << 16];
        int n;
        while ((n = in.read(buf)) > 0) {
            out.write(buf, 0, n);
        }
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
            Thread.currentThread().interrupt();
        }
    }

    @Override
    protected void onDestroy() {
        if (isFinishing()) {                         // the app is closed: so is its engine
            stopService(new Intent(this, EngineService.class));
        }
        super.onDestroy();
    }
}
