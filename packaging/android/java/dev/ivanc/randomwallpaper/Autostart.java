package dev.ivanc.randomwallpaper;

import android.app.AppOpsManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.util.Log;

import java.lang.reflect.Method;

/**
 * Xiaomi's "Autostart" switch (MIUI, HyperOS). With it off, the system
 * refuses to start the app's processes from the background, the rotation's
 * JobScheduler runs included: the wallpaper changed only while the app was
 * open. It is not an Android permission an app can ask for in its manifest;
 * the most an app can do is read it and open the screen where it is.
 *
 * Called from Python through libjnienv.so (jnienv.c, rw_autostart), with the
 * application as the context.
 */
public class Autostart {

    private static final String TAG = "RandomWallpaper";
    /** AppOpsManager's op for it on Xiaomi's systems: MIUIOP(10008). */
    private static final int OP_AUTO_START = 10008;

    static boolean isXiaomi() {
        String maker = Build.MANUFACTURER == null ? "" : Build.MANUFACTURER.toLowerCase();
        return maker.equals("xiaomi") || maker.equals("redmi") || maker.equals("poco");
    }

    /** 1 when it is on, 0 when it is off, -1 when this phone has no such
     *  switch or it cannot be read. */
    public static int state(Context context) {
        if (!isXiaomi())
            return -1;
        try {
            AppOpsManager ops = context.getSystemService(AppOpsManager.class);
            Method check = AppOpsManager.class.getMethod(
                    "checkOpNoThrow", int.class, int.class, String.class);
            int mode = (Integer) check.invoke(ops, OP_AUTO_START,
                    android.os.Process.myUid(), context.getPackageName());
            return mode == AppOpsManager.MODE_ALLOWED ? 1 : 0;
        } catch (Throwable e) {
            Log.w(TAG, "autostart: cannot read it", e);
            return -1;
        }
    }

    /** Open the screen with the switch: Xiaomi's own list, else the app's
     *  page in Settings. True if something opened. */
    public static boolean open(Context context) {
        Intent[] tries = {
            new Intent("miui.intent.action.OP_AUTO_START"),
            new Intent().setComponent(new ComponentName("com.miui.securitycenter",
                    "com.miui.permcenter.autostart.AutoStartManagementActivity")),
            new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.fromParts("package", context.getPackageName(), null)),
        };
        for (Intent intent : tries) {
            try {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(intent);
                return true;
            } catch (Exception e) {
                Log.i(TAG, "autostart: " + intent + " did not open: " + e);
            }
        }
        return false;
    }
}
