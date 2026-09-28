pluginManagement {
    val flutterSdkPath =
        run {
            val properties = java.util.Properties()
            file("local.properties").inputStream().use { properties.load(it) }
            val flutterSdkPath = properties.getProperty("flutter.sdk")
            require(flutterSdkPath != null) { "flutter.sdk not set in local.properties" }
            flutterSdkPath
        }

    includeBuild("$flutterSdkPath/packages/flutter_tools/gradle")

    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

// Android Gradle plugin 8.13: what Flutter needs (8.11.1 or later) and what Chaquopy 17 (Python in the app)
// is made for. The Kotlin plugin is for the Flutter plugins written in Kotlin; the app's own code is Java.
plugins {
    id("dev.flutter.flutter-plugin-loader") version "1.0.0"
    id("com.android.application") version "8.13.0" apply false
    id("org.jetbrains.kotlin.android") version "2.4.20" apply false
    id("com.chaquo.python") version "17.0.0" apply false
}

include(":app")
