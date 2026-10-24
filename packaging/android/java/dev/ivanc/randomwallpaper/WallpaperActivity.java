package dev.ivanc.randomwallpaper;

import android.os.Bundle;
import android.util.Log;

import java.io.File;

import org.kivy.android.PythonUtil;
import org.qtproject.qt.android.bindings.QtActivity;

/**
 * The app's activity: python-for-android's Qt PythonActivity, minus the
 * one thing that broke setting a wallpaper.
 *
 * Setting the wallpaper makes Android 12 and later re-theme the system from
 * its colours, and that recreates every activity — a change no
 * android:configChanges flag can claim. PythonActivity.onDestroy() kills the
 * whole process whatever the reason, so the app vanished each time it set a
 * wallpaper; and a subclass cannot skip that, since a call past it lands
 * right back in it. So this does what PythonActivity does — unpack the app,
 * point Python at it, let Qt start "main" — itself, and ends the process
 * only when the activity is really finishing.
 */
public class WallpaperActivity extends QtActivity {

    private static final String TAG = "RandomWallpaper";

    public static WallpaperActivity mActivity = null;

    public String getAppRoot() {
        return getFilesDir().getAbsolutePath() + "/app";
    }

    private static String entryPoint(String searchDir) {
        return new File(searchDir + "/main.pyc").exists() ? "main.pyc" : "main.py";
    }

    private static void setEnvironmentVariable(String key, String value) {
        try {
            android.system.Os.setenv(key, value, true);
        } catch (Exception e) {
            Log.e(TAG, "could not set " + key, e);
        }
    }

    /** An activity of this class has been created in this process before. */
    private static boolean created = false;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        if (created) {
            // Recreated in a process that already has Qt in it. Once Python
            // is running, Qt restarts the whole app here itself (it cannot
            // carry on across an activity-only restart); before then — a
            // recreate in the first second of a launch — it loaded itself a
            // second time and hung without ever starting Python. Either way
            // the answer is the same, so it is given here, for both: a fresh
            // task, and this process gone.
            Log.i(TAG, "recreated: restarting the app");
            startActivity(android.content.Intent.makeRestartActivityTask(getComponentName()));
            Runtime.getRuntime().exit(0);
        }
        created = true;
        mActivity = this;
        File appRoot = new File(getAppRoot());
        PythonUtil.unpackAsset(this, "private", appRoot, true);
        PythonUtil.unpackPyBundle(
                this, getApplicationInfo().nativeLibraryDir + "/libpybundle", appRoot, false);

        String root = getAppRoot();
        setEnvironmentVariable("ANDROID_ENTRYPOINT", entryPoint(root));
        setEnvironmentVariable("ANDROID_ARGUMENT", root);
        setEnvironmentVariable("ANDROID_APP_PATH", root);
        setEnvironmentVariable("ANDROID_PRIVATE", getFilesDir().getAbsolutePath());
        setEnvironmentVariable("ANDROID_UNPACK", root);
        setEnvironmentVariable("PYTHONHOME", root);
        setEnvironmentVariable("PYTHONPATH", root + ":" + root + "/lib");
        setEnvironmentVariable("PYTHONOPTIMIZE", "2");

        super.onCreate(savedInstanceState);
        mActivity = this;
    }

    @Override
    public void onDestroy() {
        boolean recreating = isChangingConfigurations();
        super.onDestroy();
        if (!recreating) {
            // Leaving for real: make sure every Python thread goes with it,
            // as PythonActivity did.
            android.os.Process.killProcess(android.os.Process.myPid());
        }
    }
}
