package gen.sparta.remix;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.util.Log;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;

/**
 * Runs the Sparta Gen engine — Python and the local web app it serves — while the app is open, as a
 * foreground service: a render goes on with the screen off or another app in front.
 */
public class EngineService extends Service {
    static final String TAG = "SpartaGen";
    private static final String CHANNEL = "engine";
    private static final int NOTIFICATION = 1;

    private static volatile int port = 0;
    private static volatile String error = null;
    private PowerManager.WakeLock wakeLock;

    /** The engine's port once it is up, else 0. */
    static int port() {
        return port;
    }

    /** Why the engine could not start, if it could not. */
    static String error() {
        return error;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        goForeground();
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "SpartaGen:engine");
        wakeLock.setReferenceCounted(false);
        wakeLock.acquire(6 * 60 * 60 * 1000L);
        new Thread(this::startEngine, "spartagen-start").start();
    }

    private void startEngine() {
        try {
            error = null;
            if (!Python.isStarted()) {
                Python.start(new AndroidPlatform(getApplicationContext()));
            }
            File home = getExternalFilesDir(null);
            if (home == null) {
                home = getFilesDir();
            }
            PyObject p = Python.getInstance().getModule("spartagen.android").callAttr("start",
                    home.getAbsolutePath(), getApplicationInfo().nativeLibraryDir,
                    getCacheDir().getAbsolutePath());
            port = p.toInt();
            Log.i(TAG, "engine listening on 127.0.0.1:" + port);
        } catch (Throwable t) {
            Log.e(TAG, "engine failed to start", t);
            error = String.valueOf(t);
        }
    }

    private void goForeground() {
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        Notification.Builder b;
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, getString(R.string.channel_engine),
                    NotificationManager.IMPORTANCE_LOW));
            b = new Notification.Builder(this, CHANNEL);
        } else {
            b = new Notification.Builder(this);
        }
        Intent open = new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent pi = PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification n = b.setSmallIcon(R.drawable.ic_stat_engine)
                .setContentTitle(getString(R.string.app_name))
                .setContentText(getString(R.string.engine_running))
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(NOTIFICATION, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        } else {
            startForeground(NOTIFICATION, n);
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (port == 0 && error != null) {                 // a failed start: try again
            new Thread(this::startEngine, "spartagen-start").start();
        }
        return START_NOT_STICKY;
    }

    /** Android 15 ends a data-sync service after six hours: stop cleanly (the app starts it again). */
    @Override
    public void onTimeout(int startId, int fgsType) {
        stopSelf();
    }

    @Override
    public void onDestroy() {
        try {
            if (Python.isStarted()) {
                Python.getInstance().getModule("spartagen.android").callAttr("stop");
            }
        } catch (Throwable t) {
            Log.w(TAG, "engine stop", t);
        }
        port = 0;
        if (wakeLock != null && wakeLock.isHeld()) {
            wakeLock.release();
        }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
