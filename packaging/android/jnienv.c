/*
 * The JNIEnv getter pyjnius links against, for python-for-android's Qt
 * bootstrap.
 *
 * p4a builds pyjnius against the "genericndkbuild" bootstraps, whose own
 * native code provides WebView_AndroidGetJNIEnv(); the Qt bootstrap does not,
 * so jnius.so failed to load ("cannot locate symbol") and nothing that goes
 * through Java — setting the wallpaper with WallpaperManager — could work.
 *
 * main.py loads this library RTLD_GLOBAL (and it is linked -z global) before
 * jnius is first imported. The Java VM comes from Qt
 * (QtAndroidPrivate::javaVM()), or failing that from JNI_GetCreatedJavaVMs;
 * the calling thread is attached if it is not yet.
 *
 * It also sets the wallpaper itself, with plain JNI, for when pyjnius still
 * cannot be had: rw_set_wallpaper(), called through ctypes.
 */
#include <dlfcn.h>
#include <jni.h>
#include <stddef.h>

typedef JavaVM *(*qt_java_vm)(void);
typedef jint (*created_vms)(JavaVM **, jsize, jsize *);

static JavaVM *vm = NULL;

/* Loaded through System.load() — by AutoJob, in the rotation's own process,
 * where there is no Qt to ask — the VM introduces itself here. */
JNIEXPORT jint JNI_OnLoad(JavaVM *loaded_by, void *reserved)
{
    (void)reserved;
    vm = loaded_by;
    return JNI_VERSION_1_6;
}

static JavaVM *find_vm(void)
{
    if (vm)
        return vm;

    const char *qt_symbol = "_ZN17QtAndroidPrivate6javaVMEv";
    void *sym = dlsym(RTLD_DEFAULT, qt_symbol);
    const char *qt_libs[] = {"libQt6Core_x86_64.so", "libQt6Core_arm64-v8a.so", NULL};
    for (int i = 0; !sym && qt_libs[i]; i++) {
        void *handle = dlopen(qt_libs[i], RTLD_NOW | RTLD_NOLOAD);
        if (handle)
            sym = dlsym(handle, qt_symbol);
    }
    if (sym)
        vm = ((qt_java_vm)sym)();

    if (!vm) {
        const char *vm_libs[] = {"libnativehelper.so", "libart.so", NULL};
        for (int i = 0; !vm && vm_libs[i]; i++) {
            void *handle = dlopen(vm_libs[i], RTLD_NOW);
            created_vms get = handle ? (created_vms)dlsym(handle, "JNI_GetCreatedJavaVMs") : NULL;
            jsize count = 0;
            if (get)
                get(&vm, 1, &count);
        }
    }
    return vm;
}

JNIEnv *WebView_AndroidGetJNIEnv(void)
{
    JavaVM *vm = find_vm();
    JNIEnv *env = NULL;
    if (!vm)
        return NULL;
    if ((*vm)->GetEnv(vm, (void **)&env, JNI_VERSION_1_6) != JNI_OK)
        /* void *: the JDK and the NDK jni.h disagree on this argument type. */
        (*vm)->AttachCurrentThread(vm, (void *)&env, NULL);
    return env;
}


static void say(char *error, size_t size, const char *message)
{
    size_t i = 0;
    for (; message[i] && i + 1 < size; i++)
        error[i] = message[i];
    error[i] = 0;
}

/* Fill `error` with the pending Java exception's message, clear it, and say
 * whether there was one. */
static int failed(JNIEnv *env, char *error, size_t size)
{
    if (!(*env)->ExceptionCheck(env))
        return 0;
    jthrowable exc = (*env)->ExceptionOccurred(env);
    (*env)->ExceptionClear(env);
    error[0] = 0;
    jclass throwable = (*env)->FindClass(env, "java/lang/Throwable");
    jmethodID to_string = throwable
        ? (*env)->GetMethodID(env, throwable, "toString", "()Ljava/lang/String;") : NULL;
    jstring text = to_string ? (jstring)(*env)->CallObjectMethod(env, exc, to_string) : NULL;
    if (text) {
        const char *chars = (*env)->GetStringUTFChars(env, text, NULL);
        say(error, size, chars);
        (*env)->ReleaseStringUTFChars(env, text, chars);
    }
    (*env)->ExceptionClear(env);
    return 1;
}

#define CHECK(what) do { \
        if (failed(env, error, size) || !(what)) { \
            if (!error[0]) \
                say(error, size, "no " #what); \
            (*env)->PopLocalFrame(env, NULL); \
            return -1; \
        } \
    } while (0)

/* WallpaperManager.getInstance(app).setStream(new FileInputStream(path)).
 * 0 when it worked; -1 with `error` filled in when it did not. */
int rw_set_wallpaper(const char *path, char *error, size_t size)
{
    JNIEnv *env = WebView_AndroidGetJNIEnv();
    error[0] = 0;
    if (!env) {
        say(error, size, "no Java VM");
        return -1;
    }
    if ((*env)->PushLocalFrame(env, 16) != 0)
        return -1;

    jclass thread = (*env)->FindClass(env, "android/app/ActivityThread");
    CHECK(thread);
    jmethodID current = (*env)->GetStaticMethodID(env, thread, "currentApplication",
                                                  "()Landroid/app/Application;");
    CHECK(current);
    jobject app = (*env)->CallStaticObjectMethod(env, thread, current);
    CHECK(app);

    jclass manager_class = (*env)->FindClass(env, "android/app/WallpaperManager");
    CHECK(manager_class);
    jmethodID get_instance = (*env)->GetStaticMethodID(env, manager_class, "getInstance",
        "(Landroid/content/Context;)Landroid/app/WallpaperManager;");
    CHECK(get_instance);
    jobject manager = (*env)->CallStaticObjectMethod(env, manager_class, get_instance, app);
    CHECK(manager);

    jclass stream_class = (*env)->FindClass(env, "java/io/FileInputStream");
    CHECK(stream_class);
    jmethodID open = (*env)->GetMethodID(env, stream_class, "<init>", "(Ljava/lang/String;)V");
    CHECK(open);
    jstring jpath = (*env)->NewStringUTF(env, path);
    CHECK(jpath);
    jobject stream = (*env)->NewObject(env, stream_class, open, jpath);
    CHECK(stream);

    jmethodID set_stream = (*env)->GetMethodID(env, manager_class, "setStream",
                                               "(Ljava/io/InputStream;)V");
    CHECK(set_stream);
    (*env)->CallVoidMethod(env, manager, set_stream, stream);
    int bad = failed(env, error, size);

    jmethodID close = (*env)->GetMethodID(env, stream_class, "close", "()V");
    if (close)
        (*env)->CallVoidMethod(env, stream, close);
    (*env)->ExceptionClear(env);
    (*env)->PopLocalFrame(env, NULL);
    return bad ? -1 : 0;
}

/* Installer.install(application, path) from Installer.java: hand a
 * downloaded .apk to Android's installer, which asks the user to confirm.
 * The class is the app's own, so it is loaded through the application's
 * class loader — FindClass on a thread Java did not start sees only the
 * system's. 0 when the session was committed; -1 with `error` filled in. */
int rw_install_apk(const char *path, char *error, size_t size)
{
    JNIEnv *env = WebView_AndroidGetJNIEnv();
    error[0] = 0;
    if (!env) {
        say(error, size, "no Java VM");
        return -1;
    }
    if ((*env)->PushLocalFrame(env, 16) != 0)
        return -1;

    jclass thread = (*env)->FindClass(env, "android/app/ActivityThread");
    CHECK(thread);
    jmethodID current = (*env)->GetStaticMethodID(env, thread, "currentApplication",
                                                  "()Landroid/app/Application;");
    CHECK(current);
    jobject app = (*env)->CallStaticObjectMethod(env, thread, current);
    CHECK(app);

    jclass context_class = (*env)->FindClass(env, "android/content/Context");
    CHECK(context_class);
    jmethodID get_loader = (*env)->GetMethodID(env, context_class, "getClassLoader",
                                               "()Ljava/lang/ClassLoader;");
    CHECK(get_loader);
    jobject loader = (*env)->CallObjectMethod(env, app, get_loader);
    CHECK(loader);
    jclass loader_class = (*env)->FindClass(env, "java/lang/ClassLoader");
    CHECK(loader_class);
    jmethodID load = (*env)->GetMethodID(env, loader_class, "loadClass",
                                         "(Ljava/lang/String;)Ljava/lang/Class;");
    CHECK(load);
    jstring name = (*env)->NewStringUTF(env, "dev.ivanc.randomwallpaper.Installer");
    CHECK(name);
    jclass installer = (jclass)(*env)->CallObjectMethod(env, loader, load, name);
    CHECK(installer);

    jmethodID install = (*env)->GetStaticMethodID(env, installer, "install",
        "(Landroid/content/Context;Ljava/lang/String;)Ljava/lang/String;");
    CHECK(install);
    jstring jpath = (*env)->NewStringUTF(env, path);
    CHECK(jpath);
    jstring result = (jstring)(*env)->CallStaticObjectMethod(env, installer, install, app, jpath);
    CHECK(result);
    const char *chars = (*env)->GetStringUTFChars(env, result, NULL);
    int bad = chars[0] != 0;
    if (bad)
        say(error, size, chars);
    (*env)->ReleaseStringUTFChars(env, result, chars);
    (*env)->PopLocalFrame(env, NULL);
    return bad ? -1 : 0;
}


/* One of the app's own classes, through the application's class loader —
 * FindClass on a thread Java did not start sees only the system's. Leaves
 * the application in *app. NULL, with `error` filled in, when it fails. */
static jclass app_class(JNIEnv *env, const char *dotted, jobject *app,
                        char *error, size_t size)
{
    jclass thread = (*env)->FindClass(env, "android/app/ActivityThread");
    jmethodID current = thread ? (*env)->GetStaticMethodID(env, thread, "currentApplication",
                                                           "()Landroid/app/Application;") : NULL;
    *app = current ? (*env)->CallStaticObjectMethod(env, thread, current) : NULL;
    if (failed(env, error, size) || !*app) {
        if (!error[0])
            say(error, size, "no application");
        return NULL;
    }
    jclass context = (*env)->FindClass(env, "android/content/Context");
    jmethodID get_loader = (*env)->GetMethodID(env, context, "getClassLoader",
                                               "()Ljava/lang/ClassLoader;");
    jobject loader = (*env)->CallObjectMethod(env, *app, get_loader);
    jclass loader_class = (*env)->FindClass(env, "java/lang/ClassLoader");
    jmethodID load = (*env)->GetMethodID(env, loader_class, "loadClass",
                                         "(Ljava/lang/String;)Ljava/lang/Class;");
    jclass found = (jclass)(*env)->CallObjectMethod(env, loader, load,
                                                    (*env)->NewStringUTF(env, dotted));
    if (failed(env, error, size) || !found) {
        if (!error[0])
            say(error, size, dotted);
        return NULL;
    }
    return found;
}

/* AutoJob.schedule(application, on): the rotation's JobScheduler job.
 * 1 when it is scheduled now, 0 when it is not, -1 on an error. */
int rw_schedule_auto(int on, char *error, size_t size)
{
    JNIEnv *env = WebView_AndroidGetJNIEnv();
    error[0] = 0;
    if (!env) {
        say(error, size, "no Java VM");
        return -1;
    }
    if ((*env)->PushLocalFrame(env, 16) != 0)
        return -1;
    jobject app = NULL;
    jclass job = app_class(env, "dev.ivanc.randomwallpaper.AutoJob", &app, error, size);
    CHECK(job);
    jmethodID schedule = (*env)->GetStaticMethodID(env, job, "schedule",
                                                   "(Landroid/content/Context;Z)Z");
    CHECK(schedule);
    jboolean now = (*env)->CallStaticBooleanMethod(env, job, schedule, app,
                                                   on ? JNI_TRUE : JNI_FALSE);
    CHECK(1);
    (*env)->PopLocalFrame(env, NULL);
    return now ? 1 : 0;
}

/* AutoJob.isScheduled(application): 1, 0, or -1 on an error. */
int rw_auto_scheduled(char *error, size_t size)
{
    JNIEnv *env = WebView_AndroidGetJNIEnv();
    error[0] = 0;
    if (!env) {
        say(error, size, "no Java VM");
        return -1;
    }
    if ((*env)->PushLocalFrame(env, 16) != 0)
        return -1;
    jobject app = NULL;
    jclass job = app_class(env, "dev.ivanc.randomwallpaper.AutoJob", &app, error, size);
    CHECK(job);
    jmethodID scheduled = (*env)->GetStaticMethodID(env, job, "isScheduled",
                                                    "(Landroid/content/Context;)Z");
    CHECK(scheduled);
    jboolean yes = (*env)->CallStaticBooleanMethod(env, job, scheduled, app);
    CHECK(1);
    (*env)->PopLocalFrame(env, NULL);
    return yes ? 1 : 0;
}
