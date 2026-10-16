#include <flutter/dart_project.h>
#include <flutter/flutter_view_controller.h>
#include <windows.h>

#include "flutter_window.h"
#include "utils.h"

int APIENTRY wWinMain(_In_ HINSTANCE instance, _In_opt_ HINSTANCE prev,
                      _In_ wchar_t *command_line, _In_ int show_command) {
  // Attach to console when present (e.g., 'flutter run') or create a
  // new console when running with a debugger.
  if (!::AttachConsole(ATTACH_PARENT_PROCESS) && ::IsDebuggerPresent()) {
    CreateAndAttachConsole();
  }

  // Initialize COM, so that it is available for use in the library and/or
  // plugins.
  ::CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED);

  flutter::DartProject project(L"data");

  // The app's Dart code runs on a thread of its own, not on this window's (Flutter merges the two by default).
  // Merged, every call the video player makes from Dart (media_kit drives libmpv over FFI) runs on this thread —
  // the one the system's Open and Save dialogs need for COM — and the dialogs failed ("Could not show dialog",
  // RPC_E_WRONG_THREAD) or hung the window (issue 6).  SPARTAGEN_MERGED_THREADS=1 merges them again (the release
  // builds' dialog check runs both ways).
  wchar_t merged[4] = {};
  if (::GetEnvironmentVariableW(L"SPARTAGEN_MERGED_THREADS", merged, 4) == 0 || merged[0] != L'1') {
    project.set_ui_thread_policy(flutter::UIThreadPolicy::RunOnSeparateThread);
  }

  std::vector<std::string> command_line_arguments =
      GetCommandLineArguments();

  project.set_dart_entrypoint_arguments(std::move(command_line_arguments));

  FlutterWindow window(project);
  Win32Window::Point origin(10, 10);
  Win32Window::Size size(1320, 860);
  if (!window.Create(L"SpartaGen", origin, size)) {
    return EXIT_FAILURE;
  }
  window.SetQuitOnClose(true);

  ::MSG msg;
  while (::GetMessage(&msg, nullptr, 0, 0)) {
    ::TranslateMessage(&msg);
    ::DispatchMessage(&msg);
  }

  ::CoUninitialize();
  return EXIT_SUCCESS;
}
