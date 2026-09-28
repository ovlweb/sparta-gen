import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path/path.dart' as p;

import '../../platform/files.dart';
import '../../state/app_state.dart';
import '../widgets/common.dart';

const _qualities = {
  'preview': ('Preview', '640×360, quick — to check it'),
  '720p': ('720p video', '1280×720, the usual upload'),
  '1080p': ('1080p video', '1920×1080, the best, slower'),
  'audio': ('Audio only', 'the mix, no picture'),
};

class ExportPage extends StatefulWidget {
  const ExportPage({super.key, required this.app});

  final AppState app;

  @override
  State<ExportPage> createState() => _ExportPageState();
}

class _ExportPageState extends State<ExportPage> {
  String _quality = '720p';

  AppState get app => widget.app;

  String get _title {
    final t = '${app.arrangementSummary?['title'] ?? ''}'.trim();
    return Files.safeName(t.isNotEmpty ? t : app.name);
  }

  void _saved(String? where) {
    if (where == null) return;
    if (Files.onPhone) {
      app.info('Saved $where.');
    } else {
      app.info('Saved to $where', action: 'Show', onAction: () => Files.reveal(where));
    }
  }

  Future<void> _saveVideo(Map<String, dynamic> out) async {
    final file = '${out['file']}';
    final q = '${out['quality']}';
    final where = await app.saveFile(
      suggestedName: '$_title${q == '1080p' || q == '720p' ? '' : ' ($q)'}.mp4',
      kind: Kinds.mp4,
      mime: 'video/mp4',
      write: (dest) => app.exportFile(file, dest),
    );
    _saved(where);
  }

  Future<void> _saveAudio(Map<String, dynamic> out, String format) async {
    final file = '${out['audio'] ?? out['file']}';
    final where = await app.saveFile(
      suggestedName: '$_title.$format',
      kind: format == 'mp3' ? Kinds.mp3 : Kinds.wav,
      mime: format == 'mp3' ? 'audio/mpeg' : 'audio/wav',
      write: (dest) => app.exportFile(file, dest, audioFormat: format),
    );
    _saved(where);
  }

  Future<void> _savePackZip() async {
    final where = await app.saveFile(
      suggestedName: '$_title - sample pack.zip',
      kind: Kinds.zip,
      mime: 'application/zip',
      write: (dest) => app.exportPack(dest),
    );
    _saved(where);
  }

  Future<void> _savePackFolder() async {
    final dir = await Files.folder(title: 'Save the sample pack here');
    if (dir == null) return;
    if (await app.exportPack(dir)) _saved(p.join(dir, '${Files.safeName(app.name)} - sample pack'));
  }

  Future<void> _saveMidi() async {
    final where = await app.saveFile(
      suggestedName: '$_title.mid',
      kind: Kinds.mid,
      mime: 'audio/midi',
      write: (dest) => app.exportMidi(dest),
    );
    _saved(where);
  }

  Future<void> _saveProjectAs() async {
    final where = await app.saveFile(
      suggestedName: '${Files.safeName(app.name)}.spartagen.json',
      kind: Kinds.json,
      mime: 'application/json',
      write: (dest) => app.saveProjectAs(dest),
    );
    if (where != null && !Files.onPhone) {
      app.info('Project saved to $where', action: 'Show', onAction: () => Files.reveal(where));
    }
  }

  @override
  Widget build(BuildContext context) {
    final outs = app.outputs;
    final order = ['1080p', '720p', 'preview', 'audio'];
    final done = [
      for (final q in order)
        if (outs[q] is Map && (outs[q] as Map)['file'] != null && File('${(outs[q] as Map)['file']}').existsSync())
          (outs[q] as Map).cast<String, dynamic>(),
    ];
    return PageBody(
      title: 'Export',
      subtitle: 'Render the remix, watch it, and save it where you want — the video, the audio, the samples or the MIDI.',
      children: [
        _renderCard(context),
        if (done.isNotEmpty) _filesCard(context, done),
        _moreCard(context),
      ],
    );
  }

  Widget _renderCard(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final can = app.hasSource && !app.busy;
    final controls = Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Text(_title, style: Theme.of(context).textTheme.titleLarge, maxLines: 2, overflow: TextOverflow.ellipsis),
      const SizedBox(height: 4),
      Text(app.builtOn, style: TextStyle(color: cs.onSurfaceVariant)),
      const SizedBox(height: 14),
      RadioGroup<String>(
        groupValue: _quality,
        onChanged: (v) => setState(() => _quality = v ?? _quality),
        child: Column(children: [
          for (final e in _qualities.entries)
            RadioListTile<String>(
              value: e.key,
              dense: true,
              contentPadding: EdgeInsets.zero,
              title: Text(e.value.$1),
              subtitle: Text(e.value.$2),
            ),
        ]),
      ),
      const SizedBox(height: 8),
      FilledButton.icon(
        style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 16)),
        onPressed: can ? () => app.render(_quality) : null,
        icon: const Icon(Icons.movie_creation_outlined),
        label: Text('Render ${_qualities[_quality]!.$1.toLowerCase()}'),
      ),
      if (!app.hasSource)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text('Open a video first.', style: TextStyle(color: cs.onSurfaceVariant)),
        ),
    ]);
    final pane = VideoPane(path: app.lastRender != null && app.lastRender!.endsWith('.mp4') ? app.lastRender : null);
    return SectionCard(
      child: LayoutBuilder(builder: (context, box) {
        if (box.maxWidth > 800) {
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(width: box.maxWidth * 0.58, child: pane),
            const SizedBox(width: 20),
            Expanded(child: controls),
          ]);
        }
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [pane, const SizedBox(height: 16), controls]);
      }),
    );
  }

  Widget _filesCard(BuildContext context, List<Map<String, dynamic>> done) {
    final cs = Theme.of(context).colorScheme;
    return SectionCard(
      title: 'Rendered',
      subtitle: 'Save a copy anywhere; the app keeps its own in the project.',
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        for (final out in done)
          Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(color: cs.surfaceContainer, borderRadius: BorderRadius.circular(10)),
            child: Wrap(spacing: 12, runSpacing: 10, crossAxisAlignment: WrapCrossAlignment.center, children: [
              Icon(out['quality'] == 'audio' ? Icons.audiotrack : Icons.movie, color: cs.primary),
              SizedBox(
                width: 230,
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(_qualities['${out['quality']}']?.$1 ?? '${out['quality']}',
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  Text(
                    '${fmtDuration(out['duration'] as num?)}'
                    '${out['lufs'] is num ? ' · ${(out['lufs'] as num).toStringAsFixed(1)} LUFS' : ''}',
                    style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12.5),
                  ),
                ]),
              ),
              if (out['quality'] != 'audio')
                OutlinedButton.icon(
                  onPressed: () => setState(() => app.lastRender = '${out['file']}'),
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('Watch'),
                ),
              if (out['quality'] != 'audio')
                FilledButton.icon(
                  onPressed: () => _saveVideo(out),
                  icon: const Icon(Icons.save_alt),
                  label: const Text('Save video…'),
                ),
              if (out['quality'] == 'audio')
                OutlinedButton.icon(
                  onPressed: () => Players.playSound('${out['audio'] ?? out['file']}', tag: 'mix'),
                  icon: const Icon(Icons.play_arrow),
                  label: const Text('Listen'),
                ),
              MenuAnchor(
                builder: (context, c, _) => FilledButton.tonalIcon(
                  onPressed: () => c.isOpen ? c.close() : c.open(),
                  icon: const Icon(Icons.audio_file_outlined),
                  label: const Text('Save audio…'),
                ),
                menuChildren: [
                  MenuItemButton(onPressed: () => _saveAudio(out, 'wav'), child: const Text('WAV (lossless)')),
                  MenuItemButton(onPressed: () => _saveAudio(out, 'mp3'), child: const Text('MP3')),
                ],
              ),
              if (!Files.onPhone)
                IconButton(
                  tooltip: 'Show the app’s copy in its folder',
                  onPressed: () => Files.reveal('${out['file']}'),
                  icon: const Icon(Icons.folder_open),
                ),
            ]),
          ),
      ]),
    );
  }

  Widget _moreCard(BuildContext context) {
    final can = app.analyzed && !app.busy;
    return SectionCard(
      title: 'Also export',
      child: Wrap(spacing: 12, runSpacing: 12, children: [
        _tile(
          context,
          icon: Icons.library_music_outlined,
          title: 'Sample pack',
          text: 'Every sample as WAV with its video clip, in the folders remixers keep.',
          actions: [
            FilledButton.tonal(onPressed: can ? _savePackZip : null, child: const Text('Save as ZIP…')),
            if (!Files.onPhone)
              OutlinedButton(onPressed: can ? _savePackFolder : null, child: const Text('Into a folder…')),
          ],
        ),
        _tile(
          context,
          icon: Icons.piano,
          title: 'MIDI',
          text: 'The remix’s notes, one track per part — to finish it in a DAW.',
          actions: [
            FilledButton.tonal(onPressed: app.busy ? null : _saveMidi, child: const Text('Export MIDI…')),
          ],
        ),
        _tile(
          context,
          icon: Icons.save_outlined,
          title: 'Project',
          text: 'Everything you set, to open it again later.',
          actions: [
            FilledButton.tonal(onPressed: app.busy ? null : app.saveProject, child: const Text('Save')),
            OutlinedButton(onPressed: app.busy ? null : _saveProjectAs, child: const Text('Save as…')),
          ],
        ),
      ]),
    );
  }

  Widget _tile(BuildContext context,
      {required IconData icon, required String title, required String text, required List<Widget> actions}) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      width: 320,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(color: cs.surfaceContainer, borderRadius: BorderRadius.circular(12)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Row(children: [
          Icon(icon, color: cs.primary),
          const SizedBox(width: 8),
          Text(title, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
        ]),
        const SizedBox(height: 6),
        Text(text, style: TextStyle(color: cs.onSurfaceVariant)),
        const SizedBox(height: 12),
        Wrap(spacing: 8, runSpacing: 8, children: actions),
      ]),
    );
  }
}
