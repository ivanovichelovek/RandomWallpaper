package dev.ivanc.randomwallpaper;

import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageInstaller;
import android.os.Build;
import android.util.Log;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Installing a downloaded update: the .apk goes into a PackageInstaller
 * session, and Android asks the user to confirm — the screen every
 * sideloaded app update goes through, and the only way an app may replace
 * itself. No FileProvider is needed, unlike handing the file to the
 * installer by URI.
 *
 * Called from Python through libjnienv.so (jnienv.c, rw_install_apk), with
 * the application as the context.
 */
public class Installer {

    private static final String TAG = "RandomWallpaper";
    private static final String ACTION = "dev.ivanc.randomwallpaper.INSTALL_STATUS";

    /** "" when the session was committed; otherwise what went wrong. */
    public static String install(final Context context, String path) {
        try {
            PackageInstaller installer = context.getPackageManager().getPackageInstaller();
            PackageInstaller.SessionParams params = new PackageInstaller.SessionParams(
                    PackageInstaller.SessionParams.MODE_FULL_INSTALL);
            params.setAppPackageName(context.getPackageName());
            int id = installer.createSession(params);
            PackageInstaller.Session session = installer.openSession(id);

            File apk = new File(path);
            try (InputStream in = new FileInputStream(apk);
                 OutputStream out = session.openWrite("base.apk", 0, apk.length())) {
                byte[] buffer = new byte[1 << 16];
                int n;
                while ((n = in.read(buffer)) > 0)
                    out.write(buffer, 0, n);
                session.fsync(out);
            }

            // The answer comes back as a broadcast: first "needs the user",
            // with the confirmation screen to show, then the outcome.
            BroadcastReceiver receiver = new BroadcastReceiver() {
                @Override
                public void onReceive(Context c, Intent intent) {
                    int status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, -999);
                    if (status == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                        Intent confirm = intent.getParcelableExtra(Intent.EXTRA_INTENT);
                        if (confirm != null) {
                            confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                            c.startActivity(confirm);
                        }
                        return;
                    }
                    Log.i(TAG, "update: " + status + " "
                            + intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE));
                    try {
                        c.unregisterReceiver(this);
                    } catch (IllegalArgumentException ignored) {
                    }
                }
            };
            IntentFilter filter = new IntentFilter(ACTION);
            if (Build.VERSION.SDK_INT >= 33)
                context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
            else
                context.registerReceiver(receiver, filter);

            // Mutable: the installer fills in the status. Bound to this
            // package, as Android 14 requires of a mutable PendingIntent.
            Intent reply = new Intent(ACTION).setPackage(context.getPackageName());
            int flags = PendingIntent.FLAG_UPDATE_CURRENT
                    | (Build.VERSION.SDK_INT >= 31 ? PendingIntent.FLAG_MUTABLE : 0);
            PendingIntent pending = PendingIntent.getBroadcast(context, id, reply, flags);
            session.commit(pending.getIntentSender());
            session.close();
            return "";
        } catch (Exception e) {
            Log.w(TAG, "update failed", e);
            return e.toString();
        }
    }
}
