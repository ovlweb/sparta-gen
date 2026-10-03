import 'dart:io';

import 'package:desktop_drop/desktop_drop.dart';
import 'package:flutter/material.dart';

import '../../platform/files.dart';
import '../../state/app_state.dart';
import '../widgets/common.dart';

class SourcePage extends StatefulWidget {
  const SourcePage({super.key, required this.app});

  final AppState app;

  @override
  State<SourcePage> createState() => _SourcePageState();
}

class _SourcePageState extends State<SourcePage> {
  final _url = TextEditingController();
  bool _dragging = false;

  AppState get app => widget.app;

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  Future<void> _open({bool photos = false}) async {
    final path = await app.pickFile(Kinds.video, photos: photos);
    if (path != null) await app.setSource(path);
  }

  /// The open button: on an iPhone or iPad a menu first — most videos there are in Photos, the rest in Files.
  Widget _openButton(Widget Function(VoidCallback? onPressed) button) {
    if (!Platform.isIOS) return button(app.busy ? null : _open);
    return MenuAnchor(
      builder: (context, c, _) => button(app.busy ? null : () => c.isOpen ? c.close() : c.open()),
      menuChildren: [
        MenuItemButton(
            leadingIcon: const Icon(Icons.photo_library_outlined),
            onPressed: () => _open(photos: true),
            child: const Text('From Photos')),
        MenuItemButton(leadingIcon: const Icon(Icons.folder_open), onPressed: _open, child: const Text('From Files')),
      ],
    );
  }

  Future<void> _download() async {
    final link = _url.text.trim();
    if (link.isEmpty) return;
    if (await app.downloadUrl(link)) _url.clear();
  }

  @override
  Widget build(BuildContext context) {
    final src = app.source;
    return PageBody(
      title: 'Source',
      subtitle: 'The video everything is cut from: its voice becomes the pitches and the chorus, its hits the '
          'percussion, its lines the quotes.',
      children: [
        src == null ? _dropZone(context) : _loaded(context, src),
        _oneClick(context),
        if (src != null) _moreVideos(context),
      ],
    );
  }

  /// More videos to cut samples from: a pitch from one, the kick from another …
  Widget _moreVideos(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final others = app.sources.where((v) => v['id'] != 'main').toList();
    Future<void> add() async {
      final path = await app.pickFile(Kinds.video);
      if (path != null) await app.addSource(path);
    }
    return SectionCard(
      title: 'More videos',
      subtitle: 'Cut samples from several videos: on the Samples page, choose the video each one comes from — the '
          'pitches from one, the kick or a hi-hat from another.',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        for (final v in others)
          ListTile(
            contentPadding: EdgeInsets.zero,
            leading: Icon(v['has_video'] == true ? Icons.movie_outlined : Icons.graphic_eq),
            title: Text('${v['name']}', overflow: TextOverflow.ellipsis),
            subtitle: Text([
              fmtDuration(v['duration'] as num?),
              if (v['analyzed'] == true) 'read' else 'read when a sample is cut from it',
            ].join(' · '), style: TextStyle(color: cs.onSurfaceVariant)),
            trailing: IconButton(
              tooltip: 'Take this video out (its samples are cut from the main video again)',
              onPressed: app.busy ? null : () => app.removeSource('${v['id']}'),
              icon: const Icon(Icons.close),
            ),
          ),
        const SizedBox(height: 4),
        AdaptiveButton.outlined(
          onPressed: app.busy ? null : add,
          icon: const Icon(Icons.video_call_outlined),
          label: const Text('Add another video…'),
        ),
      ]),
    );
  }

  Widget _linkRow() => LayoutBuilder(builder: (context, box) {
        final field = TextField(
          controller: _url,
          decoration: const InputDecoration(
            labelText: 'Or paste a link (YouTube and other sites)',
            prefixIcon: Icon(Icons.link),
          ),
          onSubmitted: (_) => _download(),
        );
        final button = AdaptiveButton.tonal(
          onPressed: app.busy ? null : _download,
          icon: const Icon(Icons.download),
          label: const Text('Download'),
        );
        if (box.maxWidth < 420) {        // a phone: the link gets the whole width
          return Column(crossAxisAlignment: CrossAxisAlignment.end, children: [field, const SizedBox(height: 8), button]);
        }
        return Row(children: [Expanded(child: field), const SizedBox(width: 10), button]);
      });

  Widget _dropZone(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final zone = AnimatedContainer(
      duration: const Duration(milliseconds: 150),
      padding: const EdgeInsets.symmetric(vertical: 40, horizontal: 20),
      decoration: BoxDecoration(
        color: _dragging ? cs.primary.withValues(alpha: 0.10) : cs.surfaceContainer,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: _dragging ? cs.primary : cs.outlineVariant, width: _dragging ? 2 : 1),
      ),
      child: Column(children: [
        Icon(Icons.video_library_outlined, size: 54, color: cs.primary),
        const SizedBox(height: 10),
        Text(Files.onPhone ? 'Choose a video from your phone' : 'Drop a video here',
            style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 4),
        Text('Any video or audio file (mp4, mkv, mov, webm, mp3, wav …)', style: TextStyle(color: cs.onSurfaceVariant)),
        const SizedBox(height: 16),
        _openButton((onPressed) => AdaptiveButton.filled(
              onPressed: onPressed,
              icon: const Icon(Icons.folder_open),
              label: const Text('Open video…'),
            )),
      ]),
    );
    return SectionCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (Files.onPhone)
          zone
        else
          DropTarget(
            onDragEntered: (_) => setState(() => _dragging = true),
            onDragExited: (_) => setState(() => _dragging = false),
            onDragDone: (d) {
              setState(() => _dragging = false);
              if (d.files.isNotEmpty) app.setSource(d.files.first.path);
            },
            child: zone,
          ),
        const SizedBox(height: 16),
        _linkRow(),
      ]),
    );
  }

  Widget _loaded(BuildContext context, Map<String, dynamic> src) {
    final cs = Theme.of(context).colorScheme;
    final hasVideo = src['has_video'] == true;
    final info = Wrap(spacing: 8, runSpacing: 8, children: [
      Pill(fmtDuration(src['duration'] as num?), icon: Icons.schedule),
      if (hasVideo) Pill('${src['width']}×${src['height']}', icon: Icons.aspect_ratio),
      if (hasVideo) Pill('${((src['fps'] as num?) ?? 0).toStringAsFixed(2)} fps', icon: Icons.speed),
      if (!hasVideo) const Pill('audio only', icon: Icons.graphic_eq),
      if (app.analyzed) Pill('samples cut', icon: Icons.check_circle, color: cs.secondary),
    ]);
    final details = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text('${src['name']}', style: Theme.of(context).textTheme.titleLarge, maxLines: 2, overflow: TextOverflow.ellipsis),
      const SizedBox(height: 10),
      info,
      const SizedBox(height: 16),
      Wrap(spacing: 10, runSpacing: 10, children: [
        _openButton((onPressed) => AdaptiveButton.outlined(
            onPressed: onPressed, icon: const Icon(Icons.swap_horiz), label: const Text('Change video…'))),
      ]),
      const SizedBox(height: 16),
      _linkRow(),
    ]);
    final player = hasVideo && src['path'] != null && File('${src['path']}').existsSync()
        ? VideoPane(path: '${src['path']}')
        : null;
    return SectionCard(
      child: LayoutBuilder(builder: (context, box) {
        if (box.maxWidth > 760 && player != null) {
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(width: box.maxWidth * 0.52, child: player),
            const SizedBox(width: 20),
            Expanded(child: details),
          ]);
        }
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (player != null) ...[player, const SizedBox(height: 16)],
          details,
        ]);
      }),
    );
  }

  Widget _oneClick(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final look = app.look;
    final styleName = look == null
        ? ''
        : '${(look['styles'] as Map?)?[(look['video'] as Map?)?['style']] ?? (look['video'] as Map?)?['style']}';
    final fxName = look == null
        ? ''
        : '${(look['fx_presets'] as Map?)?[(look['mix'] as Map?)?['fx_preset']] ?? (look['mix'] as Map?)?['fx_preset']}';
    return SectionCard(
      title: 'One click',
      subtitle: 'The samples are cut and tuned, the remix is built on your base and a preview is rendered — '
          'everything stays editable afterwards.',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 12, runSpacing: 12, crossAxisAlignment: WrapCrossAlignment.center, children: [
          AdaptiveButton.filled(
            style: FilledButton.styleFrom(
              backgroundColor: cs.secondary,
              foregroundColor: cs.onSecondary,
              padding: const EdgeInsets.symmetric(horizontal: 26, vertical: 20),
              textStyle: const TextStyle(fontSize: 17, fontWeight: FontWeight.w700),
            ),
            onPressed: app.busy || !app.hasSource ? null : () => app.makeRemix(),
            icon: const Icon(Icons.bolt, size: 26),
            label: const Text('Make my Sparta Remix'),
          ),
          AdaptiveButton.outlined(
            onPressed: app.busy || !app.hasSource
                ? null
                : () async {
                    if (await app.analyze()) app.go(AppPage.samples);
                  },
            icon: const Icon(Icons.content_cut),
            label: const Text('Only cut the samples'),
          ),
        ]),
        const SizedBox(height: 14),
        Wrap(spacing: 8, runSpacing: 8, children: [
          ActionChip(
              avatar: const Icon(Icons.queue_music, size: 18),
              label: Text('Built on: ${app.builtOn}'),
              onPressed: () => app.go(AppPage.base)),
          if (styleName.isNotEmpty)
            ActionChip(
                avatar: const Icon(Icons.auto_awesome, size: 18),
                label: Text('Look: $styleName'),
                onPressed: () => app.go(AppPage.look)),
          if (fxName.isNotEmpty)
            ActionChip(
                avatar: const Icon(Icons.graphic_eq, size: 18),
                label: Text('Sound: $fxName'),
                onPressed: () => app.go(AppPage.look)),
        ]),
        if (!app.hasSource)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Text('Open a video first.', style: TextStyle(color: cs.onSurfaceVariant)),
          ),
      ]),
    );
  }
}
