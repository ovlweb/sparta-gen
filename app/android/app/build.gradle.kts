// SpartaGen for Android: the Flutter app, the engine (the repository's Python package, run by Chaquopy in
// a foreground service) and ffmpeg built for Android (ffmpeg/build.sh → jniLibs/<abi>/libffmpeg.so).
plugins {
    id("com.android.application")
    id("com.chaquo.python")
    // The Flutter Gradle Plugin must be applied after the Android Gradle plugin.
    id("dev.flutter.flutter-gradle-plugin")
}

// The ABIs being built: Flutter says which (-Ptarget-platform=android-arm64,…); Python and ffmpeg follow.
val abiOf = mapOf(
    "android-arm64" to "arm64-v8a",
    "android-x64" to "x86_64",
    "android-arm" to "armeabi-v7a",
    "android-x86" to "x86",
)
val abiList: List<String> =
    ((findProperty("target-platform") as String?) ?: "android-arm64")
        .split(",")
        .mapNotNull { abiOf[it.trim()] }
        .ifEmpty { listOf("arm64-v8a") }

// The app's Python code is the repository's own engine, copied fresh whenever Gradle runs.
val pythonSrc = layout.buildDirectory.dir("python-src").get().asFile
project.delete(pythonSrc)
project.copy {
    from(rootProject.file("../../spartagen")) {
        exclude("**/__pycache__/**", "**/*.pyc")
    }
    into(File(pythonSrc, "spartagen"))
}

fun env(name: String): String? = System.getenv(name)?.takeIf { it.isNotEmpty() }

android {
    namespace = "gen.sparta.remix"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // The same id as the earlier SpartaGen APKs: this one installs over them.
        applicationId = "gen.sparta.remix"
        minSdk = 24
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
        ndk {
            abiFilters.clear()
            abiFilters.addAll(abiList)
        }
    }

    signingConfigs {
        create("shared") {
            // A key of your own from the environment (e.g. CI secrets); otherwise the repository's sideload
            // key, so every new APK installs over the one before (see README.md).
            storeFile = env("SPARTAGEN_KEYSTORE")?.let { file(it) } ?: rootProject.file("sideload.keystore")
            storePassword = env("SPARTAGEN_KEYSTORE_PASSWORD") ?: "android"
            keyAlias = env("SPARTAGEN_KEY_ALIAS") ?: "sparta-gen"
            keyPassword = env("SPARTAGEN_KEY_PASSWORD") ?: "android"
        }
    }

    buildTypes {
        getByName("debug") {
            signingConfig = signingConfigs.getByName("shared")
        }
        getByName("profile") {
            signingConfig = signingConfigs.getByName("shared")
        }
        getByName("release") {
            isMinifyEnabled = false
            isShrinkResources = false
            signingConfig = signingConfigs.getByName("shared")
        }
    }

    packaging {
        // ffmpeg is a program: Android only runs it from the extracted native-library folder.
        jniLibs {
            useLegacyPackaging = true
        }
    }

    lint {
        // Lint reports findings; it does not stop a build of the app.
        checkReleaseBuilds = false
        abortOnError = false
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"
        pip {
            install("numpy")
            install("yt-dlp")
        }
        // The engine reads a few files next to its code: keep the package on the filesystem.
        extractPackages("spartagen")
    }
    sourceSets {
        getByName("main") {
            srcDir(pythonSrc)
        }
    }
}

flutter {
    source = "../.."
}

// Each ABI needs its ffmpeg (bash ffmpeg/build.sh) — fail early instead of shipping an app without it.
tasks.named("preBuild") {
    doFirst {
        abiList.forEach { abi ->
            if (!file("src/main/jniLibs/$abi/libffmpeg.so").isFile) {
                throw GradleException(
                    "src/main/jniLibs/$abi/libffmpeg.so is missing: run ABIS=$abi bash ffmpeg/build.sh (in app/android)",
                )
            }
        }
    }
}
