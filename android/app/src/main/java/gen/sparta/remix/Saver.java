package gen.sparta.remix;

import android.app.Activity;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Context;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.MediaStore;
import android.util.Log;
import android.webkit.MimeTypeMap;
import android.webkit.URLUtil;
import android.widget.Toast;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/** Downloads from the web app (renders, audio, sample packs) saved where the phone keeps media. */
final class Saver {
    private Saver() {
    }

    static void save(Activity a, String url, String disposition, String mime) {
        String name = fileName(url, disposition, mime);
        Toast.makeText(a, a.getString(R.string.saving, name), Toast.LENGTH_SHORT).show();
        new Thread(() -> {
            String where = null;
            try {
                where = copy(a, url, name, mime);
            } catch (Exception e) {
                Log.e(EngineService.TAG, "save " + url, e);
            }
            String msg = where != null ? a.getString(R.string.saved, where) : a.getString(R.string.save_failed, name);
            a.runOnUiThread(() -> Toast.makeText(a, msg, Toast.LENGTH_LONG).show());
        }, "spartagen-save").start();
    }

    /** The web app names its downloads in the link (?download=…); otherwise the usual guess. */
    static String fileName(String url, String disposition, String mime) {
        String name = null;
        try {
            name = Uri.parse(url).getQueryParameter("download");
        } catch (Exception ignored) {
            // not a hierarchical uri
        }
        if (name == null || name.trim().isEmpty()) {
            name = URLUtil.guessFileName(url, disposition, mime);
        }
        return name.replaceAll("[\\\\/:*?\"<>|]", "_");
    }

    private static String copy(Context c, String url, String name, String mime) throws IOException {
        if (mime == null || mime.isEmpty() || mime.startsWith("application/octet-stream")) {
            String ext = MimeTypeMap.getFileExtensionFromUrl(name);
            String guess = ext == null ? null : MimeTypeMap.getSingleton().getMimeTypeFromExtension(ext.toLowerCase());
            mime = guess != null ? guess : "application/octet-stream";
        }
        boolean video = mime.startsWith("video/");
        boolean audio = mime.startsWith("audio/");
        String folder = video ? Environment.DIRECTORY_MOVIES : audio ? Environment.DIRECTORY_MUSIC
                : Environment.DIRECTORY_DOWNLOADS;
        HttpURLConnection conn = (HttpURLConnection) new URL(url).openConnection();
        try (InputStream in = conn.getInputStream()) {
            if (Build.VERSION.SDK_INT >= 29) {
                ContentResolver cr = c.getContentResolver();
                ContentValues v = new ContentValues();
                v.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
                v.put(MediaStore.MediaColumns.MIME_TYPE, mime);
                v.put(MediaStore.MediaColumns.RELATIVE_PATH, folder + "/SpartaGen");
                v.put(MediaStore.MediaColumns.IS_PENDING, 1);
                String volume = MediaStore.VOLUME_EXTERNAL_PRIMARY;
                Uri collection = video ? MediaStore.Video.Media.getContentUri(volume)
                        : audio ? MediaStore.Audio.Media.getContentUri(volume)
                        : MediaStore.Downloads.getContentUri(volume);
                Uri item = cr.insert(collection, v);
                if (item == null) {
                    throw new IOException("the media store refused " + name);
                }
                try (OutputStream out = cr.openOutputStream(item)) {
                    if (out == null) {
                        throw new IOException("cannot write " + item);
                    }
                    pipe(in, out);
                } catch (IOException e) {
                    cr.delete(item, null, null);
                    throw e;
                }
                v.clear();
                v.put(MediaStore.MediaColumns.IS_PENDING, 0);
                cr.update(item, v, null, null);
            } else {
                File dir = new File(Environment.getExternalStoragePublicDirectory(folder), "SpartaGen");
                if (!dir.isDirectory() && !dir.mkdirs()) {
                    throw new IOException("cannot create " + dir);
                }
                File f = new File(dir, name);
                try (OutputStream out = new FileOutputStream(f)) {
                    pipe(in, out);
                }
                MediaScannerConnection.scanFile(c, new String[]{f.getAbsolutePath()}, new String[]{mime}, null);
            }
        } finally {
            conn.disconnect();
        }
        return folder + "/SpartaGen/" + name;
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
}
