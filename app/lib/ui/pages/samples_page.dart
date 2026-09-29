import 'package:flutter/material.dart';

import '../../state/app_state.dart';
import '../widgets/common.dart';
import '../widgets/cutter.dart';

const _groups = <(String, String?, List<String>?)>[
  ('Chorus, Epicness & DunDunDenDen', 'The main phrase cut in two, and a third word — they play as they are, not tuned.',
      ['chorus_a', 'chorus_b', 'chorus_c', 'chorus_c_a', 'chorus_c_b']),
  ('Pitches', 'Tuned to the key; several play the chord lines together.', ['pitch1', 'pitch2', 'pitch3', 'pitch4', 'bass']),
  ('Percussion', 'Hits from the video, locked to the base.',
      ['kick', 'snare', 'clap', 'hat_closed', 'hat_open', 'hat2', 'perc', 'crash']),
  ('Quotes & Madness words', null, ['quote1', 'quote2', 'quote3', 'phrase', 'word_a', 'word_b']),
  ('Main phrase syllables', 'The DunDunDenDen chops.', null),
];

/// Which list of candidates a sample is picked from.
const _roleKind = {
  'chorus_a': 'word', 'chorus_b': 'word', 'chorus_c': 'word', 'chorus_c_a': 'word', 'chorus_c_b': 'word', //
  'pitch1': 'pitch', 'pitch2': 'pitch', 'pitch3': 'pitch', 'pitch4': 'pitch',
  'kick': 'kick', 'snare': 'snare', 'clap': 'snare', 'perc': 'snare',
  'hat_closed': 'hat', 'hat_open': 'hat', 'hat2': 'hat', 'crash': 'crash',
  'quote1': 'quote', 'quote2': 'quote', 'quote3': 'quote', 'phrase': 'quote',
  'word_a': 'word', 'word_b': 'word',
};

/// Both chorus parts come from one pick: the main phrase.
const _selectKey = {'chorus_a': 'chorus', 'chorus_b': 'chorus', 'chorus_c_a': 'chorus_c', 'chorus_c_b': 'chorus_c'};

const _roleName = {
  'chorus_a': 'Chorus — part 1', 'chorus_b': 'Chorus — part 2', 'chorus_c': 'Epicness — third word', //
  'chorus_c_a': 'DunDunDenDen 3A', 'chorus_c_b': 'DunDunDenDen 3B',
  'pitch1': 'Main pitch', 'pitch2': 'Second pitch', 'pitch3': 'Third pitch', 'pitch4': 'Fourth pitch', 'bass': 'Bass',
  'kick': 'Kick', 'snare': 'Snare', 'clap': 'Clap', 'hat_closed': 'Closed hat', 'hat_open': 'Open hat',
  'hat2': 'Second hi-hat', 'perc': 'Extra hit', 'crash': 'Crash',
  'quote1': 'Quote 1', 'quote2': 'Quote 2', 'quote3': 'Quote 3', 'phrase': 'Main phrase',
  'word_a': 'Madness word 1', 'word_b': 'Madness word 2',
};

class SamplesPage extends StatelessWidget {
  const SamplesPage({super.key, required this.app});

  final AppState app;

  @override
  Widget build(BuildContext context) {
    const title = 'Samples';
    const subtitle = 'Cut from your video automatically. Listen, and pick another cut when one sounds off — '
        'every candidate the analysis found is in the list.';
    if (!app.hasSource) {
      return PageBody(title: title, subtitle: subtitle, children: [
        SectionCard(
          child: EmptyState(
            icon: Icons.video_library_outlined,
            title: 'Open a video first',
            action: FilledButton(onPressed: () => app.go(AppPage.source), child: const Text('Go to Source')),
          ),
        ),
      ]);
    }
    final bank = app.bank;
    if (!app.analyzed || bank == null) {
      return PageBody(title: title, subtitle: subtitle, children: [
        SectionCard(
          child: EmptyState(
            icon: Icons.content_cut,
            title: 'The samples are not cut yet',
            message: 'It takes a minute: the voice is found, cut into pitches, words and hits, and tuned.',
            action: FilledButton.icon(
              onPressed: app.busy ? null : () => app.analyze(),
              icon: const Icon(Icons.content_cut),
              label: const Text('Cut the samples'),
            ),
          ),
        ),
      ]);
    }
    final samples = [for (final s in (bank['samples'] as List? ?? const [])) (s as Map).cast<String, dynamic>()];
    final byId = {for (final s in samples) '${s['id']}': s};
    final syllables = [for (final s in samples) if (s['role'] == 'syllable') '${s['id']}'];
    return PageBody(
      title: title,
      subtitle: subtitle,
      children: [
        _TuningCard(app: app, bank: bank),
        for (final (name, note, ids) in _groups)
          if ((ids ?? syllables).any(byId.containsKey))
            SectionCard(
              title: name,
              subtitle: note,
              child: Wrap(spacing: 12, runSpacing: 12, children: [
                for (final id in ids ?? syllables)
                  if (byId[id] != null) _SampleTile(app: app, sample: byId[id]!, bank: bank),
              ]),
            ),
      ],
    );
  }
}

class _TuningCard extends StatelessWidget {
  const _TuningCard({required this.app, required this.bank});

  final AppState app;
  final Map<String, dynamic> bank;

  @override
  Widget build(BuildContext context) {
    final cfg = (bank['config'] as Map?)?.cast<String, dynamic>() ?? {};
    final octave = cfg['pitch_octave'];
    final bassOctave = (cfg['bass_octave'] as num?)?.toInt() ?? 3;
    final flatten = (cfg['flatten'] as num?)?.toDouble() ?? 1.0;
    final auto = app.keyMode != 'manual';
    return SectionCard(
      title: 'Tuning',
      subtitle: 'Pitches are tuned to the key of your base; the chorus plays as it is.',
      child: Wrap(spacing: 16, runSpacing: 14, crossAxisAlignment: WrapCrossAlignment.center, children: [
        ActionChip(
          avatar: const Icon(Icons.music_note, size: 18),
          label: Text('Key ${app.key}${auto ? ' (follows the base)' : ''}'),
          tooltip: 'Change the key on the Base page',
          onPressed: () => app.go(AppPage.base),
        ),
        LabeledDropdown<String>(
          label: 'Pitch octave',
          width: 230,
          value: octave == null ? 'auto' : '$octave',
          items: const {'auto': 'Nearest to the voice', '2': 'Octave 2 (low)', '3': 'Octave 3', '4': 'Octave 4', '5': 'Octave 5 (high)'},
          enabled: !app.busy,
          onChanged: (v) => app.sampleConfig({'pitch_octave': v == 'auto' ? null : int.parse(v)}),
        ),
        LabeledDropdown<int>(
          label: 'Bass octave',
          width: 150,
          value: bassOctave,
          items: const {1: 'Octave 1', 2: 'Octave 2', 3: 'Octave 3', 4: 'Octave 4'},
          enabled: !app.busy,
          onChanged: (v) => app.sampleConfig({'bass_octave': v}),
        ),
        SliderRow(
          label: 'Straight notes',
          value: flatten,
          min: 0,
          max: 1,
          divisions: 20,
          format: (v) => '${(v * 100).round()}%',
          onChanged: (v) => app.sampleConfig({'flatten': double.parse(v.toStringAsFixed(2))}),
        ),
        OutlinedButton.icon(
          onPressed: app.busy ? null : () => app.analyze(force: true),
          icon: const Icon(Icons.refresh),
          label: const Text('Cut again'),
        ),
      ]),
    );
  }
}

class _SampleTile extends StatefulWidget {
  const _SampleTile({required this.app, required this.sample, required this.bank});

  final AppState app;
  final Map<String, dynamic> sample;
  final Map<String, dynamic> bank;

  @override
  State<_SampleTile> createState() => _SampleTileState();
}

class _SampleTileState extends State<_SampleTile> {
  Map<String, dynamic> get s => widget.sample;
  String get id => '${s['id']}';
  String get selectKey => _selectKey[id] ?? id;

  dynamic get selection => ((widget.bank['config'] as Map?)?['selections'] as Map?)?[selectKey];

  /// Where the sample is cut now, in seconds of the video (the main phrase: both its parts, cut as one).
  (double, double) _currentCut() {
    final sel = selection;
    if (sel is Map && sel['start'] is num && sel['end'] is num) {
      return ((sel['start'] as num).toDouble(), (sel['end'] as num).toDouble());
    }
    final all = [for (final x in (widget.bank['samples'] as List? ?? const [])) (x as Map).cast<String, dynamic>()];
    Map<String, dynamic>? byId(String k) => all.where((x) => x['id'] == k).firstOrNull;
    double at(Map<String, dynamic>? m, String k, double fallback) => ((m?[k] as num?) ?? fallback).toDouble();
    final a = at(s, 'src_start', 0);
    final z = at(s, 'src_end', a + 0.5);
    if (selectKey == 'chorus') return (at(byId('chorus_a'), 'src_start', a), at(byId('chorus_b'), 'src_end', z));
    if (selectKey == 'chorus_c') return (at(byId('chorus_c'), 'src_start', a), at(byId('chorus_c'), 'src_end', z));
    return (a, z);
  }

  Future<void> _cutIt() async {
    final app = widget.app;
    final (a, z) = _currentCut();
    final duration = ((widget.bank['analysis'] as Map?)?['duration'] as num?)?.toDouble() ?? z + 5;
    final cut = await showSampleCutter(
      context,
      app: app,
      title: selectKey == 'chorus' ? 'the main phrase (both Chorus parts)' : (_roleName[id] ?? id),
      start: a,
      end: z,
      sourceDuration: duration,
      sourcePath: app.source?['path'] as String?,
    );
    if (cut == null) return;
    await app.selectSample(selectKey, start: cut.$1, end: cut.$2);
  }

  String _meta() {
    final m = (s['meta'] as Map?)?.cast<String, dynamic>() ?? {};
    final role = s['role'];
    if (role == 'pitch' && m['source_note'] != null) {
      final st = (m['shift_semitones'] as num?) ?? 0;
      return '${m['source_note']} → ${s['root_note']} (${st > 0 ? '+' : ''}$st st)';
    }
    if (role == 'bass') return '${s['root_note']} from ${m['from'] ?? 'the main pitch'}';
    if (role == 'kick') return m['shift_semitones'] != null && m['shift_semitones'] != 0 ? 'pitched ${m['shift_semitones']} st for body' : 'kick from the video';
    if ((role == 'syllable' || role == 'word') && m['tuned_to'] != null) return 'tuned copy on ${m['tuned_to']}';
    if (role == 'chorus') return 'main phrase, as it is · cut at ${m['split'] ?? 'the middle'}';
    return '';
  }

  @override
  Widget build(BuildContext context) {
    final app = widget.app;
    final cs = Theme.of(context).colorScheme;
    final t = Theme.of(context).textTheme;
    final kind = _roleKind[id];
    final cands = kind == null ? const [] : ((widget.bank['candidates'] as Map?)?[kind] as List? ?? const []);
    final sel = selection;
    final selIdx = sel is int ? sel : (sel is num ? sel.toInt() : null);
    final note = s['root_note'];
    final srcPath = app.source?['path'] as String?;
    final meta = _meta();

    return ValueListenableBuilder<String?>(
      valueListenable: Players.playing,
      builder: (context, playing, _) {
        final isPlaying = playing == id || playing == '$id:orig';
        return SizedBox(
          width: 268,
          child: Card(
            color: isPlaying ? cs.primary.withValues(alpha: 0.10) : cs.surfaceContainer,
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(12),
              side: BorderSide(color: isPlaying ? cs.primary : cs.outlineVariant.withValues(alpha: 0.5)),
            ),
            clipBehavior: Clip.antiAlias,
            child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
              InkWell(
                onTap: () => Players.playSound(app.engine.url('${s['audio_url']}'), tag: id),
                child: AspectRatio(
                  aspectRatio: 16 / 9,
                  child: Stack(fit: StackFit.expand, children: [
                    Image.network(
                      app.engine.url('${s['thumb_url']}'),
                      fit: BoxFit.cover,
                      errorBuilder: (_, _, _) => Container(color: Colors.black, child: const Icon(Icons.graphic_eq, color: Colors.white38)),
                    ),
                    Positioned(
                      left: 8,
                      top: 8,
                      child: _tag(_roleName[id] ?? '${s['label'] ?? id}', Colors.black.withValues(alpha: 0.65), Colors.white),
                    ),
                    if (note != null && s['role'] != 'chorus')
                      Positioned(right: 8, top: 8, child: _tag('$note', cs.secondary, cs.onSecondary)),
                    Center(
                      child: Icon(isPlaying && playing == id ? Icons.graphic_eq : Icons.play_circle_fill,
                          size: 42, color: Colors.white.withValues(alpha: 0.85)),
                    ),
                  ]),
                ),
              ),
              Padding(
                padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  Text.rich(TextSpan(children: [
                    TextSpan(text: '${fmtTime(s['src_start'] as num?)} – ${fmtTime(s['src_end'] as num?)}',
                        style: const TextStyle(fontWeight: FontWeight.w600)),
                    TextSpan(
                        text: '  ·  ${((s['duration'] as num?) ?? 0).toStringAsFixed(2)} s',
                        style: TextStyle(color: cs.onSurfaceVariant)),
                  ])),
                  if (meta.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(meta, style: t.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
                    ),
                  const SizedBox(height: 8),
                  Row(children: [
                    Expanded(
                      child: FilledButton.tonalIcon(
                        style: _compact,
                        onPressed: () => Players.playSound(app.engine.url('${s['audio_url']}'), tag: id),
                        icon: const Icon(Icons.play_arrow, size: 18),
                        label: const Text('Play'),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: OutlinedButton.icon(
                        style: _compact,
                        onPressed: srcPath == null
                            ? null
                            : () => Players.playSound(srcPath,
                                tag: '$id:orig', start: (s['src_start'] as num?)?.toDouble(), end: (s['src_end'] as num?)?.toDouble()),
                        icon: const Icon(Icons.hearing, size: 18),
                        label: const Text('Original'),
                      ),
                    ),
                  ]),
                  if (kind != null) ...[
                    const SizedBox(height: 10),
                    LabeledDropdown<int>(
                      label: 'Cut',
                      width: double.infinity,
                      value: sel is Map ? -2 : (selIdx ?? -1),
                      enabled: !app.busy,
                      items: {
                        -1: 'Automatic (best)',
                        if (sel is Map) -2: 'My own cut',
                        for (var i = 0; i < cands.length; i++) i: _candLabel(i, (cands[i] as Map).cast<String, dynamic>()),
                      },
                      onChanged: (v) {
                        if (v == -2) return;
                        if (v == -1) {
                          app.selectSample(selectKey, reset: true);
                        } else {
                          app.selectSample(selectKey, index: v);
                        }
                      },
                    ),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton.icon(
                        onPressed: app.busy ? null : _cutIt,
                        icon: const Icon(Icons.content_cut, size: 18),
                        label: Text(sel is Map ? 'Change my cut' : 'Cut it myself'),
                      ),
                    ),
                  ],
                ]),
              ),
            ]),
          ),
        );
      },
    );
  }

  static final _compact = ButtonStyle(
    padding: const WidgetStatePropertyAll(EdgeInsets.symmetric(horizontal: 10)),
    visualDensity: VisualDensity.compact,
  );

  static String _candLabel(int i, Map<String, dynamic> c) {
    final info = (c['info'] as Map?) ?? {};
    final noteTxt = c['kind'] == 'pitch' && info['note'] != null ? ' ${info['note']}' : '';
    return '#${i + 1}  ${fmtTime(c['start'] as num?)} (${((c['duration'] as num?) ?? 0).toStringAsFixed(2)} s)$noteTxt';
  }

  static Widget _tag(String text, Color bg, Color fg) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(6)),
        child: Text(text, style: TextStyle(color: fg, fontSize: 12, fontWeight: FontWeight.w600)),
      );
}
