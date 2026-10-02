import Flutter
import PhotosUI
import UIKit
import UniformTypeIdentifiers

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    if let registrar = engineBridge.pluginRegistry.registrar(forPlugin: "SpartaGenHost") {
      AppHost.register(with: registrar)
    }
  }
}

/// What the iOS host does for the Flutter side, like the Android host: starts the engine inside the app and
/// hands over its port and secret token ("gen.sparta/engine"); picks videos from Photos, and saves files through
/// the share sheet — Photos, Files, AirDrop … ("gen.sparta/files").
final class AppHost: NSObject, PHPickerViewControllerDelegate {
  private static let token = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
  private let registrar: FlutterPluginRegistrar
  private var picked: FlutterResult?

  private init(registrar: FlutterPluginRegistrar) {
    self.registrar = registrar
  }

  static func register(with registrar: FlutterPluginRegistrar) {
    let host = AppHost(registrar: registrar)
    FlutterMethodChannel(name: "gen.sparta/engine", binaryMessenger: registrar.messenger())
      .setMethodCallHandler { call, result in host.engine(call, result) }
    FlutterMethodChannel(name: "gen.sparta/files", binaryMessenger: registrar.messenger())
      .setMethodCallHandler { call, result in host.files(call, result) }
  }

  private func engine(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    guard call.method == "start" else {
      result(FlutterMethodNotImplemented)
      return
    }
    DispatchQueue.global(qos: .userInitiated).async {
      var error: NSString?
      let port = SpartaGenEngine.start(withToken: AppHost.token, error: &error)
      DispatchQueue.main.async {
        if let port = port {
          result(["port": port, "token": AppHost.token])
        } else {
          result(FlutterError(code: "engine", message: (error as String?) ?? "The engine did not start.", details: nil))
        }
      }
    }
  }

  private func files(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    guard let presenter = registrar.viewController else {
      result(FlutterError(code: "files", message: "There is no window to show that in.", details: nil))
      return
    }
    let args = call.arguments as? [String: Any] ?? [:]
    switch call.method {
    case "open":
      pickVideo(from: presenter, images: args["images"] as? Bool ?? false, result)
    case "saveAs":
      guard let path = args["path"] as? String else {
        result(FlutterError(code: "files", message: "Nothing to save.", details: nil))
        return
      }
      share(path, from: presenter, result)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  /// A video (with [images]: or a picture or GIF) from Photos, copied into the app (its path), or nil when the
  /// user cancels.
  private func pickVideo(from presenter: UIViewController, images: Bool = false,
                         _ result: @escaping FlutterResult) {
    var config = PHPickerConfiguration()
    config.filter = images ? .any(of: [.videos, .images]) : .videos
    config.selectionLimit = 1
    // A video as it is (no conversion first); a picture as one ffmpeg reads (JPEG rather than HEIC).
    config.preferredAssetRepresentationMode = images ? .compatible : .current
    let picker = PHPickerViewController(configuration: config)
    picker.delegate = self
    picked?(nil)
    picked = result
    presenter.present(picker, animated: true)
  }

  func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
    picker.dismiss(animated: true)
    guard let result = picked else { return }
    picked = nil
    guard let provider = results.first?.itemProvider else {
      result(nil)
      return
    }
    let types = provider.registeredTypeIdentifiers.compactMap { UTType($0) }
    let type = (types.first { $0.conforms(to: .movie) } ?? types.first { $0.conforms(to: .gif) }
      ?? types.first { $0.conforms(to: .jpeg) } ?? types.first { $0.conforms(to: .png) }
      ?? types.first { $0.conforms(to: .image) })?.identifier ?? UTType.movie.identifier
    provider.loadFileRepresentation(forTypeIdentifier: type) { url, error in
      var copy: URL?
      if let url = url {    // (Photos deletes this file when the block returns)
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("picked", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let dest = dir.appendingPathComponent(url.lastPathComponent)
        try? FileManager.default.removeItem(at: dest)
        if (try? FileManager.default.copyItem(at: url, to: dest)) != nil {
          copy = dest
        }
      }
      DispatchQueue.main.async {
        if let copy = copy {
          result(copy.path)
        } else {
          result(FlutterError(code: "files", message: error?.localizedDescription ?? "Could not read that file.",
                              details: nil))
        }
      }
    }
  }

  /// The share sheet for a file the app wrote: true when it went somewhere.
  private func share(_ path: String, from presenter: UIViewController, _ result: @escaping FlutterResult) {
    let sheet = UIActivityViewController(activityItems: [URL(fileURLWithPath: path)], applicationActivities: nil)
    var answered = false
    sheet.completionWithItemsHandler = { _, completed, _, _ in
      if !answered {
        answered = true
        result(completed)
      }
    }
    if let popover = sheet.popoverPresentationController {   // iPad: from the middle of the window
      popover.sourceView = presenter.view
      popover.sourceRect = CGRect(x: presenter.view.bounds.midX, y: presenter.view.bounds.midY, width: 0, height: 0)
      popover.permittedArrowDirections = []
    }
    presenter.present(sheet, animated: true)
  }
}
