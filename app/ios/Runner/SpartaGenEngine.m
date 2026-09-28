#import "SpartaGenEngine.h"

#import <Python/Python.h>

#include <signal.h>
#include <stdint.h>
#include <string.h>

#import <ffmpegkit/FFmpegKit.h>
#import <ffmpegkit/FFmpegKitConfig.h>
#import <ffmpegkit/FFprobeKit.h>

/// ffmpeg as a function: one command line per call (argv[0] is "ffmpeg" or "ffprobe"), everything it printed
/// written to log_path, its exit code returned.  The engine runs its command lines through it (from Python,
/// with ctypes — see spartagen/ffmpeg_function.py); several can run at once.
static int SGRunFFmpeg(int argc, const char **argv, const char *log_path) {
    @autoreleasepool {
        NSMutableArray<NSString *> *arguments = [NSMutableArray array];
        for (int i = 1; i < argc; i++) {
            [arguments addObject:[NSString stringWithUTF8String:argv[i]] ?: @""];
        }
        BOOL probe = argc > 0 && strcmp(argv[0], "ffprobe") == 0;
        AbstractSession *session = probe ? [FFprobeKit executeWithArguments:arguments]
                                         : [FFmpegKit executeWithArguments:arguments];
        if (log_path != NULL) {
            NSString *printed = [session getOutput] ?: @"";
            [printed writeToFile:@(log_path) atomically:NO encoding:NSUTF8StringEncoding error:nil];
        }
        ReturnCode *code = [session getReturnCode];
        return code != nil ? [code getValue] : 1;
    }
}

/// The Python exception being raised, as text with its traceback.
static NSString *SGPythonError(void) {
    PyObject *type = NULL, *value = NULL, *traceback = NULL;
    PyErr_Fetch(&type, &value, &traceback);
    PyErr_NormalizeException(&type, &value, &traceback);
    NSString *text = @"the engine failed";
    PyObject *module = PyImport_ImportModule("traceback");
    PyObject *lines = module && value ? PyObject_CallMethod(module, "format_exception", "OOO", type ? type : Py_None,
                                                           value, traceback ? traceback : Py_None) : NULL;
    PyObject *empty = PyUnicode_FromString("");
    PyObject *joined = lines && empty ? PyUnicode_Join(empty, lines) : NULL;
    const char *utf8 = joined ? PyUnicode_AsUTF8(joined) : NULL;
    if (utf8 != NULL) {
        text = @(utf8);
    }
    Py_XDECREF(joined);
    Py_XDECREF(empty);
    Py_XDECREF(lines);
    Py_XDECREF(module);
    Py_XDECREF(type);
    Py_XDECREF(value);
    Py_XDECREF(traceback);
    PyErr_Clear();
    return text;
}

/// Starts Python: its standard library, the engine (app/) and the packages it needs (app_packages/) are in the
/// app — put there by app/ios/Engine/install.sh.  Returns what went wrong, or nil.
static NSString *SGStartPython(void) {
    NSString *resources = NSBundle.mainBundle.resourcePath;
    NSString *lib = [NSString stringWithFormat:@"%@/python/lib/python%d.%d", resources, PY_MAJOR_VERSION, PY_MINOR_VERSION];
    NSArray<NSString *> *paths = @[
        lib,
        [lib stringByAppendingPathComponent:@"lib-dynload"],
        [resources stringByAppendingPathComponent:@"app_packages"],
        [resources stringByAppendingPathComponent:@"app"],
    ];
    PyPreConfig preconfig;
    PyConfig config;
    PyStatus status;

    PyPreConfig_InitIsolatedConfig(&preconfig);
    preconfig.utf8_mode = 1;
    status = Py_PreInitialize(&preconfig);
    if (PyStatus_Exception(status)) {
        return [NSString stringWithFormat:@"Python did not start: %s", status.err_msg ? status.err_msg : "?"];
    }
    PyConfig_InitIsolatedConfig(&config);
    config.buffered_stdio = 0;          // (its output shows in the device log at once)
    config.write_bytecode = 0;          // the app is read-only
    config.install_signal_handlers = 1; // among them: a closed pipe is an error, not the end of the app
    config.module_search_paths_set = 1;
    NSString *home = [resources stringByAppendingPathComponent:@"python"];
    status = PyConfig_SetBytesString(&config, &config.home, home.fileSystemRepresentation);
    if (!PyStatus_Exception(status)) {
        status = PyConfig_Read(&config);
    }
    for (NSString *path in paths) {
        if (PyStatus_Exception(status)) break;
        wchar_t *wide = Py_DecodeLocale(path.fileSystemRepresentation, NULL);
        status = wide ? PyWideStringList_Append(&config.module_search_paths, wide) : PyStatus_NoMemory();
        PyMem_RawFree(wide);
    }
    if (!PyStatus_Exception(status)) {
        status = Py_InitializeFromConfig(&config);
    }
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        return [NSString stringWithFormat:@"Python did not start: %s", status.err_msg ? status.err_msg : "?"];
    }
    PyEval_SaveThread();                // let the engine's threads run
    return nil;
}

@implementation SpartaGenEngine

static BOOL SGPythonStarted = NO;

+ (void)initialize {
    if (self == [SpartaGenEngine class]) {
        // ffmpeg runs inside the app: writing to a pipe whose reader has gone must be an error, not the end of
        // the app — and the app's signals stay the app's.
        signal(SIGPIPE, SIG_IGN);
        for (NSNumber *s in @[@(SignalInt), @(SignalQuit), @(SignalPipe), @(SignalTerm), @(SignalXcpu)]) {
            [FFmpegKitConfig ignoreSignal:(Signal)s.unsignedIntegerValue];
        }
        [FFmpegKitConfig setSessionHistorySize:999];   // a long render's encoder keeps its log to the end
        [FFmpegKitConfig setLogRedirectionStrategy:LogRedirectionStrategyNeverPrintLogs];
    }
}

+ (nullable NSNumber *)startWithToken:(NSString *)token error:(NSString *_Nullable *_Nullable)error {
    @synchronized (self) {
        if (!SGPythonStarted) {
            NSString *failed = SGStartPython();
            if (failed != nil) {
                if (error) *error = failed;
                return nil;
            }
            SGPythonStarted = YES;
        }
    }
    NSFileManager *fm = NSFileManager.defaultManager;
    // The engine's workspace (projects, samples, renders): the app's own, not backed up to iCloud (media).
    NSURL *supportURL = [fm URLsForDirectory:NSApplicationSupportDirectory inDomains:NSUserDomainMask].firstObject;
    NSURL *workspace = [supportURL URLByAppendingPathComponent:@"SpartaGen" isDirectory:YES];
    [fm createDirectoryAtURL:workspace withIntermediateDirectories:YES attributes:nil error:nil];
    [workspace setResourceValue:@YES forKey:NSURLIsExcludedFromBackupKey error:nil];
    NSString *support = supportURL.path;
    NSString *cache = [NSTemporaryDirectory() stringByAppendingPathComponent:@"engine"];
    NSString *info = nil;
#ifdef DEBUG
    info = [support stringByAppendingPathComponent:@"engine.json"];   // debug builds: the simulator test reads it
#endif

    NSNumber *port = nil;
    PyGILState_STATE gil = PyGILState_Ensure();
    PyObject *ios = PyImport_ImportModule("spartagen.ios");
    PyObject *result = ios ? PyObject_CallMethod(ios, "start", "sssKz", support.fileSystemRepresentation,
                                                 cache.fileSystemRepresentation, token.UTF8String,
                                                 (unsigned long long)(uintptr_t)&SGRunFFmpeg,
                                                 info ? info.fileSystemRepresentation : NULL) : NULL;
    long value = result ? PyLong_AsLong(result) : -1;
    if (result == NULL || PyErr_Occurred()) {
        if (error) *error = SGPythonError();
    } else {
        port = @(value);
    }
    Py_XDECREF(result);
    Py_XDECREF(ios);
    PyGILState_Release(gil);
    return port;
}

@end
