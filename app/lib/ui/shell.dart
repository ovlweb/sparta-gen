import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../platform/android_host.dart';
import '../platform/files.dart';
import '../state/app_state.dart';
import '../state/settings.dart';
import 'about.dart';
import 'update_dialog.dart';
import 'pages/base_page.dart';
import 'pages/export_page.dart';
import 'pages/look_page.dart';
import 'pages/remix_page.dart';
import 'pages/samples_page.dart';
import 'pages/source_page.dart';
import 'widgets/common.dart';

const _pages = <AppPage, (String, IconData, IconData)>{
  AppPage.source: ('Source', Icons.video_library_outlined, Icons.video_library),
  AppPage.base: ('Base', Icons.queue_music_outlined, Icons.queue_music),
  AppPage.samples: ('Samples', Icons.content_cut_outlined, Icons.content_cut),
  AppPage.remix: ('Remix', Icons.view_timeline_outlined, Icons.view_timeline),
  AppPage.look: ('Look & sound', Icons.auto_awesome_outlined, Icons.auto_awesome),
  AppPage.export: ('Export', Icons.ios_share_outlined, Icons.ios_share),
};

/// The app's window: navigation, the menu, the progress of a running job, and the current page.
class Shell extends StatefulWidget {
  const Shell({super.key, required this.app, required this.settings, this.onQuit});

  final AppState app;
  final AppSettings settings;
  final Future<void> Function()? onQuit;

  @override
  State<Shell> createState() => _ShellState();
}

class _ShellState extends State<Shell> {
  final _messenger = GlobalKey<ScaffoldMessengerState>();
  StreamSubscription<AppMessage>? _sub;

  AppState get app => widget.app;
  bool get _desktop => !Platform.isAndroid && !Platform.isIOS;

  @override
  void initState() {
    super.initState();
    _sub = app.messages.listen(_show);
    if (widget.settings.checkUpdates) WidgetsBinding.instance.addPostFrameCallback((_) => _lookForUpdate());
  }

  /// A new SpartaGen out? Said once, at the top, until it is taken or put off.
  Future<void> _lookForUpdate() async {
    final info = await app.checkUpdate(quiet: true);
    if (info == null || info['newer'] != true || !mounted) return;
    final m = _messenger.currentState;
    void close() => m?.hideCurrentMaterialBanner();
    m?.showMaterialBanner(MaterialBanner(
      leading: const Icon(Icons.system_update_alt),
      content: Text('SpartaGen ${info['latest']} is out (you have ${info['current']}).'),
      actions: [
        TextButton(onPressed: close, child: const Text('Later')),
        FilledButton(
          onPressed: () {
            close();
            showUpdates(context, app, widget.settings, info: info, onQuit: widget.onQuit);
          },
          child: const Text('See the update'),
        ),
      ],
    ));
  }

  void _updates() => showUpdates(context, app, widget.settings, onQuit: widget.onQuit);

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  void _show(AppMessage m) {
    final cs = Theme.of(context).colorScheme;
    _messenger.currentState
      ?..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(
        content: Row(children: [
          Icon(m.error ? Icons.error_outline : Icons.check_circle_outline,
              color: m.error ? cs.errorContainer : cs.secondary),
          const SizedBox(width: 12),
          Expanded(child: Text(m.text)),
        ]),
        duration: Duration(seconds: m.error ? 8 : 5),
        persist: false, // a message with a button still goes away by itself
        action: m.action == null ? null : SnackBarAction(label: m.action!, onPressed: m.onAction ?? () {}),
        showCloseIcon: m.error,
      ));
  }

  // ── actions ──
  Future<void> _openProject() async {
    final path = await app.pickFile(Kinds.json);
    if (path != null && mounted && await confirmLeave(context, app)) await app.openProject(path);
  }

  Future<void> _recent() async {
    var list = await app.recentProjects();
    if (!mounted) return;
    final path = await showDialog<String>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialog) => SimpleDialog(
          title: const Text('Recent projects'),
          children: [
            if (list.isEmpty)
              const Padding(padding: EdgeInsets.all(20), child: Text('No projects yet.')),
            for (final pr in list)
              SimpleDialogOption(
                onPressed: () => Navigator.pop(context, '${pr['path']}'),
                child: ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.folder_special_outlined),
                  title: Text('${pr['name'] ?? 'Untitled'}'),
                  subtitle: Text([
                    if (pr['source'] != null) '${pr['source']}',
                    if (pr['modified'] != null) _ago(pr['modified']),
                    if (pr['saved'] == false) 'never saved' else if (pr['changed'] == true) 'changes not saved',
                  ].join(' · ')),
                  trailing: IconButton(
                    tooltip: 'Delete this project',
                    icon: const Icon(Icons.delete_outline),
                    onPressed: () async {
                      if (!await _confirmDelete(context, '${pr['name'] ?? 'Untitled'}')) return;
                      final left = await app.deleteProject('${pr['path']}');
                      setDialog(() => list = left);
                    },
                  ),
                ),
              ),
          ],
        ),
      ),
    );
    if (path != null && path.isNotEmpty && mounted && await confirmLeave(context, app)) await app.openProject(path);
  }

  static Future<bool> _confirmDelete(BuildContext context, String name) async =>
      await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: Text('Delete “$name”?'),
          content: const Text('The project and its folder go: its renders and cut samples too (videos you saved '
              'elsewhere stay). This cannot be undone.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
            FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Delete')),
          ],
        ),
      ) ==
      true;

  static String _ago(dynamic ts) {
    final t = (ts as num?)?.toDouble();
    if (t == null) return '';
    final d = DateTime.fromMillisecondsSinceEpoch((t * 1000).round());
    return '${d.year}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';
  }

  Future<void> _rename() async {
    final c = TextEditingController(text: app.name);
    final name = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Name of the project'),
        content: TextField(
          controller: c,
          autofocus: true,
          decoration: const InputDecoration(labelText: 'Name'),
          onSubmitted: (v) => Navigator.pop(context, v),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, c.text), child: const Text('Rename')),
        ],
      ),
    );
    c.dispose();
    if (name != null && name.trim().isNotEmpty) await app.rename(name.trim());
  }

  Future<void> _newProject() async {
    if (await confirmLeave(context, app)) await app.newProject();
  }

  Future<void> _quit() async {
    if (await confirmLeave(context, app)) await widget.onQuit!();
  }

  Future<void> _saveAs() async {
    final where = await app.saveFile(
      suggestedName: '${Files.safeName(app.name)}.spartagen.json',
      kind: Kinds.json,
      mime: 'application/json',
      write: app.saveProjectAs,
    );
    if (where != null && !Files.onPhone) {
      app.info('Project saved to $where', action: 'Show', onAction: () => Files.reveal(where));
    }
  }

  void _about() => showAbout(context, version: app.version);

  // ── menus ──
  List<_Menu> get _menus => [
        _Menu('File', [
          _Item('New project', _newProject, const SingleActivator(LogicalKeyboardKey.keyN, control: true)),
          _Item('Open project…', _openProject, const SingleActivator(LogicalKeyboardKey.keyO, control: true)),
          _Item('Recent projects…', _recent, null),
          null,
          _Item('Save project', app.saveProject, const SingleActivator(LogicalKeyboardKey.keyS, control: true)),
          _Item('Save project as…', _saveAs, const SingleActivator(LogicalKeyboardKey.keyS, control: true, shift: true)),
          _Item('Rename project…', _rename, null),
          if (widget.onQuit != null) ...[
            null,
            _Item('Quit', _quit, const SingleActivator(LogicalKeyboardKey.keyQ, control: true)),
          ],
        ]),
        _Menu('Remix', [
          _Item('Open video…', () async {
            final path = await app.pickFile(Kinds.video);
            if (path != null) await app.setSource(path);
          }, null),
          null,
          _Item('Make my Sparta Remix', () => app.hasSource ? app.makeRemix() : app.go(AppPage.source),
              const SingleActivator(LogicalKeyboardKey.enter, control: true)),
          _Item('Cut the samples', () => app.hasSource ? app.analyze() : app.go(AppPage.source), null),
          _Item('Render a preview', () => app.hasSource ? app.render('preview') : app.go(AppPage.source),
              const SingleActivator(LogicalKeyboardKey.keyR, control: true)),
          _Item('Stop the sound', Players.stopSound, const SingleActivator(LogicalKeyboardKey.period, control: true)),
          null,
          for (final (i, pg) in AppPage.values.indexed)
            _Item(_pages[pg]!.$1, () => app.go(pg), SingleActivator(LogicalKeyboardKey(0x31 + i), control: true)),
        ]),
        _Menu('View', [
          for (final m in ThemeMode.values) _Item(AppSettings.nameOf(m), () => widget.settings.setTheme(m), null),
        ]),
        _Menu('Help', [
          _Item('Sparta Remix Wiki', () => openLink(wikiUrl), null),
          _Item('Krasen (CassidyBOTRR) on YouTube', () => openLink(krasenChannel), null),
          _Item('Krasen (composition-cassidy) on GitHub', () => openLink(krasenGithub), null),
          null,
          _Item('Check for updates…', _updates, null),
          _Item('About SpartaGen', _about, null),
        ]),
      ];

  Map<ShortcutActivator, VoidCallback> get _shortcuts {
    final map = <ShortcutActivator, VoidCallback>{};
    for (final m in _menus) {
      for (final it in m.items) {
        if (it?.shortcut == null) continue;
        final s = it!.shortcut!;
        map[s] = it.run;
        if (Platform.isMacOS) {
          map[SingleActivator(s.trigger, meta: true, shift: s.shift, alt: s.alt)] = it.run;
        }
      }
    }
    return map;
  }

  Widget _menuBar() {
    return MenuBar(
      style: MenuStyle(
        backgroundColor: WidgetStatePropertyAll(Theme.of(context).colorScheme.surfaceContainerLowest),
        elevation: const WidgetStatePropertyAll(0),
        padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 4)),
      ),
      children: [
        for (final m in _menus)
          SubmenuButton(
            menuChildren: [
              for (final it in m.items)
                if (it == null)
                  const Divider(height: 8)
                else
                  MenuItemButton(
                    onPressed: app.busy && it.heavy ? null : it.run,
                    shortcut: it.shortcut,
                    child: Text(it.label),
                  ),
            ],
            child: Text(m.label),
          ),
      ],
    );
  }

  Widget _platformMenus(Widget child) {
    return PlatformMenuBar(
      menus: [
        PlatformMenu(label: 'SpartaGen', menus: [
          PlatformMenuItem(label: 'About SpartaGen', onSelected: _about),
          if (PlatformProvidedMenuItem.hasMenu(PlatformProvidedMenuItemType.quit))
            const PlatformProvidedMenuItem(type: PlatformProvidedMenuItemType.quit),
        ]),
        for (final m in _menus)
          PlatformMenu(label: m.label, menus: [
            for (final group in _groups(m.items))
              PlatformMenuItemGroup(members: [
                for (final it in group)
                  PlatformMenuItem(
                    label: it.label,
                    onSelected: it.run,
                    shortcut: it.shortcut == null
                        ? null
                        : SingleActivator(it.shortcut!.trigger, meta: true, shift: it.shortcut!.shift),
                  ),
              ]),
          ]),
      ],
      child: child,
    );
  }

  static List<List<_Item>> _groups(List<_Item?> items) {
    final out = <List<_Item>>[[]];
    for (final it in items) {
      if (it == null) {
        if (out.last.isNotEmpty) out.add([]);
      } else if (it.label != 'Quit' && it.label != 'About SpartaGen') {
        out.last.add(it);
      }
    }
    return out.where((g) => g.isNotEmpty).toList();
  }

  // ── layout ──
  Widget _page() {
    final app = this.app;
    final child = switch (app.page) {
      AppPage.source => SourcePage(app: app),
      AppPage.base => BasePage(app: app),
      AppPage.samples => SamplesPage(app: app),
      AppPage.remix => RemixPage(app: app),
      AppPage.look => LookPage(app: app),
      AppPage.export => ExportPage(app: app),
    };
    return KeyedSubtree(key: ValueKey(app.page), child: child);
  }

  Widget _jobBar() {
    final j = app.job;
    final cs = Theme.of(context).colorScheme;
    final working = app.working;
    return AnimatedSize(
      duration: const Duration(milliseconds: 180),
      child: j == null
          ? (working == null
              ? const SizedBox(width: double.infinity)
              : Material(
                  color: cs.primary.withValues(alpha: 0.10),
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(20, 12, 20, 12),
                    child: Row(children: [
                      const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.6)),
                      const SizedBox(width: 14),
                      Expanded(child: Text(working, style: const TextStyle(fontWeight: FontWeight.w600))),
                    ]),
                  ),
                ))
          : Material(
              color: cs.primary.withValues(alpha: 0.10),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 10, 12, 10),
                child: Row(children: [
                  SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(strokeWidth: 2.6, value: j.progress > 0 ? j.progress : null),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('${app.jobLabel} — ${(j.progress * 100).round()}%',
                          style: const TextStyle(fontWeight: FontWeight.w600)),
                      const SizedBox(height: 4),
                      LinearProgressIndicator(value: j.progress > 0 ? j.progress : null, minHeight: 5,
                          borderRadius: BorderRadius.circular(3)),
                      if (j.message.isNotEmpty) ...[
                        const SizedBox(height: 3),
                        Text(j.message, maxLines: 1, overflow: TextOverflow.ellipsis,
                            style: TextStyle(fontSize: 12.5, color: cs.onSurfaceVariant)),
                      ],
                    ]),
                  ),
                  const SizedBox(width: 12),
                  AdaptiveButton.text(
                    onPressed: j.id.isEmpty ? null : app.cancelJob,
                    icon: const Icon(Icons.stop_circle_outlined),
                    label: const Text('Cancel'),
                  ),
                ]),
              ),
            ),
    );
  }

  Widget _projectTitle({bool compact = false}) {
    final cs = Theme.of(context).colorScheme;
    return InkWell(
      onTap: _rename,
      borderRadius: BorderRadius.circular(8),
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Flexible(
            child: Text(app.name,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontWeight: FontWeight.w600, fontSize: compact ? 17 : 15)),
          ),
          if (app.changed)
            Tooltip(
              message: app.saved ? 'Changes not saved' : 'Not saved yet',
              child: Padding(
                key: const ValueKey('unsaved'),
                padding: const EdgeInsets.only(left: 6),
                child: Icon(Icons.circle, size: 9, color: cs.secondary),
              ),
            ),
          const SizedBox(width: 6),
          Icon(Icons.edit, size: 15, color: cs.onSurfaceVariant),
        ]),
      ),
    );
  }

  Widget _desktopLayout(BuildContext context, BoxConstraints box) {
    final cs = Theme.of(context).colorScheme;
    // On a computer the side panel is its icons alone (their words show on the pointer); a tablet keeps the words.
    final words = !iconButtons(context);
    final extended = words && box.maxWidth >= 1180;
    Widget icon(String label, IconData data) => words ? Icon(data) : Tooltip(message: label, child: Icon(data));
    final rail = NavigationRail(
      extended: extended,
      minExtendedWidth: 200,
      labelType: words && !extended ? NavigationRailLabelType.all : NavigationRailLabelType.none,
      selectedIndex: app.page.index,
      onDestinationSelected: (i) => app.go(AppPage.values[i]),
      leading: Padding(
        padding: const EdgeInsets.fromLTRB(0, 8, 0, 16),
        child: extended
            ? const Row(mainAxisSize: MainAxisSize.min, children: [
                AppLogo(size: 36),
                SizedBox(width: 10),
                Text('SpartaGen', style: TextStyle(fontWeight: FontWeight.w800, fontSize: 18)),
              ])
            : const Tooltip(message: 'SpartaGen', child: AppLogo(size: 36)),
      ),
      trailing: Expanded(
        child: Align(
          alignment: Alignment.bottomCenter,
          child: Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: IconButton(tooltip: 'About SpartaGen', onPressed: _about, icon: const Icon(Icons.info_outline)),
          ),
        ),
      ),
      destinations: [
        for (final pg in AppPage.values)
          NavigationRailDestination(
            icon: icon(_pages[pg]!.$1, _pages[pg]!.$2),
            selectedIcon: icon(_pages[pg]!.$1, _pages[pg]!.$3),
            label: Text(_pages[pg]!.$1),
          ),
      ],
    );
    return Row(children: [
      rail,
      VerticalDivider(width: 1, color: cs.outlineVariant.withValues(alpha: 0.5)),
      Expanded(
        child: Column(children: [
          Container(
            color: cs.surfaceContainerLowest,
            height: 40,
            child: Row(children: [
              if (!Platform.isMacOS) _menuBar(),
              // The project's name and base shorten (…) before anything spills over on a narrow window.
              Expanded(
                child: Row(mainAxisAlignment: MainAxisAlignment.end, children: [
                  IconButton(
                    tooltip: AppSettings.nameOf(widget.settings.theme),
                    onPressed: widget.settings.nextTheme,
                    icon: Icon(AppSettings.iconOf(widget.settings.theme), size: 20),
                  ),
                  const SizedBox(width: 4),
                  Flexible(child: _projectTitle()),
                  const SizedBox(width: 6),
                  if (app.variant.isNotEmpty) Flexible(child: Pill(app.builtOn, icon: Icons.queue_music, ellipsis: true)),
                  const SizedBox(width: 12),
                ]),
              ),
            ]),
          ),
          _jobBar(),
          const SoundBar(),
          Expanded(child: _page()),
        ]),
      ),
    ]);
  }

  Widget _phoneLayout(BuildContext context) {
    final scaffold = Scaffold(
      appBar: AppBar(
        titleSpacing: 8,
        title: Row(children: [
          const AppLogo(size: 30),
          const SizedBox(width: 8),
          Expanded(child: _projectTitle(compact: true)),
        ]),
        actions: [
          PopupMenuButton<VoidCallback>(
            onSelected: (fn) => fn(),
            itemBuilder: (context) => [
              for (final m in _menus)
                for (final it in m.items)
                  if (it != null && it.label != 'Quit' && !it.label.startsWith('Krasen') && !_pages.values.any((p) => p.$1 == it.label))
                    PopupMenuItem(value: it.run, enabled: !(app.busy && it.heavy), child: Text(it.label)),
            ],
          ),
        ],
      ),
      body: Column(children: [_jobBar(), const SoundBar(), Expanded(child: _page())]),
      bottomNavigationBar: NavigationBar(
        selectedIndex: app.page.index,
        onDestinationSelected: (i) => app.go(AppPage.values[i]),
        labelBehavior: NavigationDestinationLabelBehavior.onlyShowSelected,
        destinations: [
          for (final pg in AppPage.values)
            NavigationDestination(icon: Icon(_pages[pg]!.$2), selectedIcon: Icon(_pages[pg]!.$3), label: _pages[pg]!.$1),
        ],
      ),
    );
    if (!Platform.isAndroid) return scaffold;
    // Back goes to the first page, then leaves the app running in the background (renders go on).
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (didPop) return;
        if (app.page != AppPage.source) {
          app.go(AppPage.source);
        } else {
          AndroidHost.background();
        }
      },
      child: scaffold,
    );
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: app,
      builder: (context, _) {
        final body = LayoutBuilder(builder: (context, box) {
          final wide = box.maxWidth >= 720;
          if (!wide || !_desktop && box.maxWidth < 900) return _phoneLayout(context);
          return Scaffold(body: _desktopLayout(context, box));
        });
        Widget root = ScaffoldMessenger(key: _messenger, child: body);
        if (_desktop) root = CallbackShortcuts(bindings: _shortcuts, child: Focus(autofocus: true, child: root));
        if (Platform.isMacOS) root = _platformMenus(root);
        return root;
      },
    );
  }
}

/// Before the project is left (a new one, another opened, the app quit): its changes saved, let go, or staying
/// with it.  True when it may be left.
Future<bool> confirmLeave(BuildContext context, AppState app) async {
  if (!app.changed) return true;
  final choice = await showDialog<String>(
    context: context,
    builder: (context) => AlertDialog(
      title: Text('Save the changes to “${app.name}”?'),
      content: Text(app.saved
          ? 'If you don’t save them, the project goes back to how you saved it last.'
          : 'This project was never saved: if you don’t save it, it is deleted.'),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context, 'cancel'), child: const Text('Cancel')),
        TextButton(onPressed: () => Navigator.pop(context, 'discard'), child: const Text('Don’t save')),
        FilledButton(onPressed: () => Navigator.pop(context, 'save'), child: const Text('Save')),
      ],
    ),
  );
  if (choice == 'save') {
    await app.saveProject();
    return !app.changed;
  }
  if (choice == 'discard') {
    await app.discardProject();
    return true;
  }
  return false;
}

class _Menu {
  const _Menu(this.label, this.items);
  final String label;
  final List<_Item?> items; // null: a divider
}

class _Item {
  _Item(this.label, this.action, this.shortcut, {bool? heavy}) : heavy = heavy ?? _heavy.contains(label);

  static const _heavy = {'Make my Sparta Remix', 'Cut the samples', 'Render a preview', 'New project', 'Open project…', 'Recent projects…', 'Open video…'};

  final String label;
  final FutureOr<void> Function() action;
  final SingleActivator? shortcut;
  final bool heavy;

  void run() => action();
}
