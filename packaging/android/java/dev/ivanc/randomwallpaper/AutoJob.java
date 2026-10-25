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

/**
 * The rotation while the app is closed: what systemd, launchd and Task
 * Scheduler do on a desktop, done by Android's JobScheduler.
 *
 * Every 15 minutes (the shortest period Android allows; it may stretch them
 * to save battery) it starts Python in a process of its own, ":auto" —
 * declared in the manifest by build-apk.sh — and runs auto.py, which is
 * `random-wallpaper --auto --quiet`. The process ends with the run: Python
 * cannot be started twice in one process, and nothing is left behind.
 *
 * auto.py ends the job itself, through done(): python-for-android's
 * nativeStart() never comes back from a script. It finalizes Python and
 * calls exit() on this thread, and exit() with the Java VM still running
 * crashed the process — before jobFinished(), so to the system every run,
 * even one that had set the wallpaper, was a job that died half-way.
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

    /** The job running in this process, for done(). */
    private static AutoJob running;
    private static JobParameters runningParams;

    /**
     * The run is over: tell the system, then end this process. Called by
     * auto.py through libjnienv.so (rw_auto_done), or below if Python could
     * not start at all. Never returns.
     */
    public static void done() {
        AutoJob job;
        JobParameters params;
        synchronized (AutoJob.class) {
            job = running;
            params = runningParams;
            running = null;
            runningParams = null;
        }
        if (job != null)
            job.jobFinished(params, false);
        // Python is done with this process; the next run gets a new one.
        // A moment first: jobFinished() reaches the system asynchronously,
        // and a process gone before it does reads as a job cut short —
        // run again at once, and again.
        try {
            Thread.sleep(2000);
        } catch (InterruptedException ignored) {
        }
        android.os.Process.killProcess(android.os.Process.myPid());
    }

    /** Closer together than this, a run is skipped before Python starts. */
    private static final long MIN_GAP_MS = 5 * 60 * 1000L;

    @Override
    public boolean onStartJob(final JobParameters params) {
        // JobScheduler can bring a periodic job round far sooner than its
        // period (seen on the emulator: every minute or so). A rotation run
        // a few minutes after the last has nothing to do, and each one
        // starts a Python: skip it cheaply.
        android.content.SharedPreferences seen = getSharedPreferences("auto", MODE_PRIVATE);
        long now = System.currentTimeMillis();
        long last = seen.getLong("last_run", 0);
        if (now - last < MIN_GAP_MS && now >= last) {
            Log.i(TAG, "rotation skipped: ran " + (now - last) / 1000 + " s ago");
            return false;
        }
        seen.edit().putLong("last_run", now).commit();
        synchronized (AutoJob.class) {
            running = this;
            runningParams = params;
        }
        new Thread(() -> {
            try {
                File filesDir = getFilesDir();
                String root = filesDir.getAbsolutePath() + "/app";
                // The app's files are unpacked by its activity; a job that
                // comes first (after an update, before the app was opened)
                // has nothing to run yet.
                if (new File(root, "auto.py").exists()) {
                    loadPython(new File(getApplicationInfo().nativeLibraryDir));
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
            // Only reached when Python did not run auto.py to its end.
            done();
        }).start();
        return true;
    }

    /**
     * What PythonUtil.loadLibraries() does, for the Qt bootstrap's names: it
     * looks for "libmain.so", and this build's is libmain_<abi>.so. The C++
     * runtime and OpenSSL first, then libpython, then main.
     */
    private static void loadPython(File libsDir) {
        File[] files = libsDir.listFiles();
        if (files == null)
            throw new RuntimeException("no native libraries in " + libsDir);
        String[] order = {"libc++_shared", "libffi", "libsqlite3", "libcrypto", "libssl",
                          "libpython3", "libmain_"};
        for (String prefix : order) {
            for (File f : files) {
                String name = f.getName();
                if (name.startsWith(prefix) && name.endsWith(".so"))
                    System.load(f.getAbsolutePath());
            }
        }
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;    // cut short by the system: try again later
    }
}
