// Updates without going to GitHub: the newest SpartaGen, downloaded and put in place of this one (a computer),
// handed to the system's installer (Android), or to TrollStore, SideStore or AltStore (an iPhone or iPad — iOS
// lets no app install apps itself; an app installed with a certificate of one's own is updated by hand).

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../platform/files.dart';
import '../state/app_state.dart';
import '../state/settings.dart';
import 'about.dart';

/// An app TrollStore installed: TrollStore leaves its mark ("_TrollStore") beside the app it installs.
bool get installedByTrollStore {
  if (!Platform.isIOS) return false;
  try {
    final container = File(Platform.resolvedExecutable).parent.parent.path;
    return File('$container/_TrollStore').existsSync() || File('$container/_TrollStoreLite').existsSync();
  } catch (_) {
    return false;
  }
}

/// Look for an update and show what there is ([info]: what a look found already).  [onQuit] quits the app, for
/// a computer's update to take its place.
Future<void> showUpdates(BuildContext context, AppState app, AppSettings settings,
    {Map<String, dynamic>? info, Future<void> Function()? onQuit}) async {
  final found = info ?? await app.checkUpdate();
  if (found == null || !context.mounted) return;
  await showDialog<void>(
    context: context,
    builder: (_) => UpdateDialog(app: app, settings: settings, info: found, onQuit: onQuit),
  );
}

const _stores = [('trollstore', 'TrollStore'), ('sidestore', 'SideStore'), ('altstore', 'AltStore')];

class UpdateDialog extends StatefulWidget {
  const UpdateDialog({super.key, required this.app, required this.settings, required this.info, this.onQuit});

  final AppState app;
  final AppSettings settings;
  final Map<String, dynamic> info;
  final Future<void> Function()? onQuit;

  @override
  State<UpdateDialog> createState() => _UpdateDialogState();
}

class _UpdateDialogState extends State<UpdateDialog> {
  final Map<String, bool> _here = {}; // iOS: the installer apps found on this iPhone or iPad
  bool _working = false;

  Map<String, dynamic> get info => widget.info;
  bool get newer => info['newer'] == true;

  @override
  void initState() {
    super.initState();
    if (Platform.isIOS) _findStores();
  }

  Future<void> _findStores() async {
    _here['trollstore'] = installedByTrollStore;
    for (final k in ['sidestore', 'altstore']) {
      try {
        _here[k] = await canLaunchUrl(Uri.parse('$k://'));
      } catch (_) {
        _here[k] = false;
      }
    }
    if (mounted) setState(() {});
  }

  /// A computer: download, put in place, restart.  Android: download, then the system's installer.
  Future<void> _update() async {
    setState(() => _working = true);
    try {
      final r = await widget.app.downloadUpdate();
      if (r == null) return; // (it said why, or it was cancelled)
      if (Platform.isAndroid) {
        final how = await Files.installApk('${r['file']}');
        if (how == 'permission') {
          widget.app.info('Allow SpartaGen to install apps (the setting just opened), then tap Update again.');
        }
        return;
      }
      if (r['app'] == null) return;
      if (await widget.app.installUpdate('${r['app']}')) {
        widget.app.info('SpartaGen starts again as ${r['version']}…');
        await widget.onQuit?.call();
      }
    } finally {
      if (mounted) setState(() => _working = false);
    }
  }

  Future<void> _openStore(String key) async {
    final link = '${((info['stores'] as Map?)?[key] as Map?)?['link'] ?? ''}';
    if (link.isEmpty) return;
    final ok = await launchUrl(Uri.parse(link), mode: LaunchMode.externalApplication).catchError((_) => false);
    if (!ok) widget.app.fail('That app is not on this iPhone or iPad.');
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final t = Theme.of(context).textTheme;
    final notes = '${info['notes'] ?? ''}'.trim();
    final asset = (info['asset'] as Map?)?.cast<String, dynamic>();
    final size = ((asset?['size'] as num?) ?? 0) / 1e6;
    final busy = _working || widget.app.busy;
    return AlertDialog(
      title: Text(newer ? 'SpartaGen ${info['latest']} is out' : 'SpartaGen is up to date'),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 480),
        child: SingleChildScrollView(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(newer
                ? 'You have ${info['current']}.${size > 0 ? ' The update is ${size.toStringAsFixed(0)} MB.' : ''}'
                : 'You have ${info['current']}, the newest there is.'),
            if (newer && notes.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text('What is new', style: t.titleSmall),
              const SizedBox(height: 4),
              Container(
                constraints: const BoxConstraints(maxHeight: 220),
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(color: cs.surfaceContainerHigh, borderRadius: BorderRadius.circular(8)),
                child: SingleChildScrollView(child: SelectableText(notes, style: t.bodySmall)),
              ),
            ],
            if (newer && Platform.isIOS) ..._iosChoices(context),
            if (newer && Platform.isAndroid) ...[
              const SizedBox(height: 10),
              Text('It installs over this one; your projects stay. Android asks once to allow SpartaGen to install '
                  'apps.', style: t.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
            ],
            const SizedBox(height: 8),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              dense: true,
              title: const Text('Look for updates when SpartaGen starts'),
              value: widget.settings.checkUpdates,
              onChanged: (v) => setState(() => widget.settings.setCheckUpdates(v)),
            ),
          ]),
        ),
      ),
      actions: [
        TextButton(onPressed: () => openLink('${info['page']}'), child: const Text('Release page')),
        TextButton(onPressed: () => Navigator.pop(context), child: Text(newer ? 'Later' : 'Close')),
        if (newer && !Platform.isIOS && asset != null)
          FilledButton.icon(
            onPressed: busy ? null : _update,
            icon: _working
                ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2))
                : const Icon(Icons.system_update_alt),
            label: Text(Platform.isAndroid ? 'Download and install' : 'Update and restart'),
          ),
      ],
    );
  }

  /// iOS: the apps that install an IPA from a link (the ones found here first), or the IPA to install by hand.
  List<Widget> _iosChoices(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final t = Theme.of(context).textTheme;
    final sorted = [..._stores]..sort((a, b) => (_here[b.$1] == true ? 1 : 0) - (_here[a.$1] == true ? 1 : 0));
    return [
      const SizedBox(height: 12),
      Text('Install it with', style: t.titleSmall),
      const SizedBox(height: 6),
      Wrap(spacing: 8, runSpacing: 8, children: [
        for (final (key, name) in sorted)
          _here[key] == true
              ? FilledButton(onPressed: () => _openStore(key), child: Text(name))
              : OutlinedButton(onPressed: () => _openStore(key), child: Text(name)),
        TextButton.icon(
          onPressed: () => openLink('${(info['asset'] as Map?)?['url'] ?? info['page']}'),
          icon: const Icon(Icons.download),
          label: const Text('The IPA'),
        ),
      ]),
      const SizedBox(height: 8),
      Text(
          'TrollStore installs it over this app (turn on “URL Scheme Enabled” in TrollStore’s settings first); '
          'SideStore and AltStore sign it again with your Apple ID. Installed with a certificate of your own '
          '(Sideloadly, ESign …)? iOS lets no app replace itself: download the IPA and install it the way you '
          'installed this one.',
          style: t.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
    ];
  }
}
