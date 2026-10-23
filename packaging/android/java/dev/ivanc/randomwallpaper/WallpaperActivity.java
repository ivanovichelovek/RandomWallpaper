package dev.ivanc.randomwallpaper;

import android.util.Log;

import java.lang.invoke.MethodHandle;
import java.lang.invoke.MethodHandles;
import java.lang.invoke.MethodType;

import org.kivy.android.PythonActivity;

/**
 * python-for-android's activity, surviving a recreate.
 *
 * Setting the wallpaper makes Android 12 and later re-theme the system from
 * its colours, and that recreates every activity — a change no
 * android:configChanges flag can claim. PythonActivity.onDestroy() kills the
 * whole process whatever the reason, so the app vanished each time it set a
 * wallpaper. Here a destroy that is only a configuration change goes to Qt's
 * own onDestroy, which knows to keep the app running, and skips the kill.
 */
public class WallpaperActivity extends PythonActivity {

    @Override
    public void onDestroy() {
        if (isChangingConfigurations()) {
            try {
                // super.super.onDestroy(): Qt's, without PythonActivity's kill.
                // The nearest class above PythonActivity that declares it —
                // QtActivity inherits it from QtActivityBase.
                Class<?> owner = PythonActivity.class.getSuperclass();
                while (owner != null && !declaresOnDestroy(owner))
                    owner = owner.getSuperclass();
                MethodHandle qt = MethodHandles.lookup().findSpecial(
                        owner, "onDestroy",
                        MethodType.methodType(void.class), WallpaperActivity.class);
                qt.invoke(this);
                return;
            } catch (Throwable e) {
                Log.w("RandomWallpaper", "could not keep the app across a recreate", e);
            }
        }
        super.onDestroy();
    }

    private static boolean declaresOnDestroy(Class<?> c) {
        try {
            c.getDeclaredMethod("onDestroy");
            return true;
        } catch (NoSuchMethodException e) {
            return false;
        }
    }
}
