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

  Future<void> _open() async {
    final path = await app.pickFile(Kinds.video);
    if (path != null) await app.setSource(path);
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
      ],
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
        final button = FilledButton.tonalIcon(
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
        Text(Files.onAndroid ? 'Choose a video from your phone' : 'Drop a video here',
            style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 4),
        Text('Any video or audio file (mp4, mkv, mov, webm, mp3, wav …)', style: TextStyle(color: cs.onSurfaceVariant)),
        const SizedBox(height: 16),
        FilledButton.icon(
          onPressed: app.busy ? null : _open,
          icon: const Icon(Icons.folder_open),
          label: const Text('Open video…'),
        ),
      ]),
    );
    return SectionCard(
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        if (Files.onAndroid)
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
        OutlinedButton.icon(
            onPressed: app.busy ? null : _open, icon: const Icon(Icons.swap_horiz), label: const Text('Change video…')),
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
          FilledButton.icon(
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
          OutlinedButton.icon(
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
