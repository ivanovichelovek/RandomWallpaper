package dev.ivanc.randomwallpaper;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.util.Log;

import java.io.File;

import org.kivy.android.PythonService;
import org.kivy.android.PythonUtil;

/**
 * The rotation while the app is closed: what systemd, launchd and Task
 * Scheduler do on a desktop, done by Android's JobScheduler.
 *
 * Every 15 minutes (the shortest period Android allows; it may stretch them
 * to save battery) it starts Python in a process of its own, ":auto" —
 * declared in the manifest by build-apk.sh — and runs auto.py, which is
 * `random-wallpaper --auto --quiet`. The process ends with the run: Python
 * cannot be started twice in one process, and nothing is left behind.
 */
public class AutoJob extends JobService {

    private static final String TAG = "RandomWallpaper";
    static final int ID = 7101;

    /** Turn the job on or off; true if it is now scheduled. */
    public static boolean schedule(Context context, boolean on) {
        JobScheduler scheduler = context.getSystemService(JobScheduler.class);
        if (!on) {
            scheduler.cancel(ID);
            return false;
        }
        JobInfo job = new JobInfo.Builder(ID, new ComponentName(context, AutoJob.class))
                .setPeriodic(15 * 60 * 1000L)
                .setPersisted(true)                     // and after a reboot
                .build();
        return scheduler.schedule(job) == JobScheduler.RESULT_SUCCESS;
    }

    public static boolean isScheduled(Context context) {
        return context.getSystemService(JobScheduler.class).getPendingJob(ID) != null;
    }

    @Override
    public boolean onStartJob(final JobParameters params) {
        new Thread(() -> {
            try {
                File filesDir = getFilesDir();
                String root = filesDir.getAbsolutePath() + "/app";
                File appRoot = new File(root);
                // The app's files are unpacked by its activity; a job that
                // comes first (after an update, before the app was opened)
                // has nothing to run yet.
                if (new File(root, "auto.py").exists()) {
                    PythonUtil.loadLibraries(appRoot, new File(getApplicationInfo().nativeLibraryDir));
                    // The JNI helper, through System.load so it learns the Java
                    // VM in JNI_OnLoad — there is no Qt in this process to ask.
                    File helper = new File(root, "libjnienv.so");
                    if (helper.exists())
                        System.load(helper.getAbsolutePath());
                    PythonService.nativeStart(
                            filesDir.getAbsolutePath(), root, "auto.py", "python",
                            root, root + ":" + root + "/lib", "");
                }
            } catch (Throwable e) {
                Log.w(TAG, "the rotation did not run", e);
            }
            jobFinished(params, false);
            // Python is done with this process; the next run gets a new one.
            android.os.Process.killProcess(android.os.Process.myPid());
        }).start();
        return true;
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;    // cut short by the system: try again later
    }
}
