/*
 * The JNIEnv getter pyjnius links against, for python-for-android's Qt
 * bootstrap.
 *
 * p4a builds pyjnius against the "genericndkbuild" bootstraps, whose own
 * native code provides WebView_AndroidGetJNIEnv(); the Qt bootstrap does not,
 * so jnius.so failed to load ("cannot locate symbol") and nothing that goes
 * through Java — setting the wallpaper with WallpaperManager — could work.
 *
 * main.py loads this library RTLD_GLOBAL before jnius is first imported. The
 * Java VM comes from Qt (QtAndroidPrivate::javaVM()), or failing that from
 * JNI_GetCreatedJavaVMs; the calling thread is attached if it is not yet.
 */
#include <dlfcn.h>
#include <jni.h>
#include <stddef.h>

typedef JavaVM *(*qt_java_vm)(void);
typedef jint (*created_vms)(JavaVM **, jsize, jsize *);

static JavaVM *find_vm(void)
{
    static JavaVM *vm = NULL;
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
