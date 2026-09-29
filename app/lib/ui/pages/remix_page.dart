import 'dart:convert';
import 'dart:math';

import 'package:flutter/material.dart';

import '../../state/app_state.dart';
import '../widgets/common.dart';

const _layouts = {
  'main': 'Main + boxes',
  'full': 'Full screen',
  'split2': 'Split in two',
  'grid3': '3×3 grid',
  'grid4': '4×4 grid',
};

const _layoutIcons = {
  'main': Icons.dashboard_outlined,
  'full': Icons.crop_din,
  'split2': Icons.vertical_split_outlined,
  'grid3': Icons.grid_view,
  'grid4': Icons.apps,
};

/// Each picture's boxes (x, y, w, h from 0 to 1), as the engine lays them out.
List<Rect> _layoutBoxes(String layout) {
  Rect r(double x, double y, double w, double h) => Rect.fromLTWH(x, y, w, h);
  List<Rect> grid(int n) => [
        for (var row = 0; row < n; row++)
          for (var col = 0; col < n; col++) r(col / n, row / n, 1 / n, 1 / n),
      ];
  return switch (layout) {
    'main' => [
        r(0.2, 0.2, 0.6, 0.6),
        for (var i = 0; i < 5; i++) r(0.2 * i, 0, 0.2, 0.2),
        for (var i = 0; i < 5; i++) r(0.2 * i, 0.8, 0.2, 0.2),
        r(0, 0.2, 0.2, 0.6),
        r(0.8, 0.2, 0.2, 0.6),
      ],
    'full' => [r(0, 0, 1, 1)],
    'split2' => [r(0, 0, 0.5, 1), r(0.5, 0, 0.5, 1)],
    'grid4' => grid(4),
    _ => grid(3),
  };
}

/// Which pattern families fit which kind of track.
const _trackSections = {
  'pitch': ['chorus', 'dundundenden', 'epicness', 'awesomeness', 'execution', 'madness', 'intro', 'chords', 'freestyle'],
  'chop': ['dundundenden', 'intro', 'chorus', 'execution'],
  'words': ['madness_words', 'freestyle'],
  'bass': ['dundundenden', 'chorus', 'intro', 'execution'],
  'drum': ['percussion', 'hihat'],
  'oneshot': <String>[],
};

const _addable = [
  'intro', 'intro_hits', 'chorus', 'dundundenden', 'epicness', 'chords', 'awesomeness1', 'awesomeness2', //
  'madness', 'execution', 'chorus_final', 'ending',
];

const _defaultSamples = [
  'pitch1', 'pitch2', 'pitch3', 'pitch4', 'bass', 'chorus_a', 'chorus_b', 'chorus_c', 'kick', 'snare', 'clap', //
  'hat_closed', 'hat_open', 'hat2', 'perc', 'crash', 'quote1', 'quote2', 'quote3', 'phrase', 'word_a', 'word_b',
];

class RemixPage extends StatefulWidget {
  const RemixPage({super.key, required this.app});

  final AppState app;

  @override
  State<RemixPage> createState() => _RemixPageState();
}

class _RemixPageState extends State<RemixPage> {
  Map<String, dynamic>? _arr; // the structure being edited
  Map<String, dynamic>? _from; // the engine's copy it was made from
  bool _dirty = false;
  bool _requested = false;
  final Set<int> _open = {};
  final _title = TextEditingController();
  final _titleFocus = FocusNode();
  int _gen = 0; // bumped whenever the list is rebuilt, so the text fields start over
  int _sel = 0; // the part shown under the timeline
  double _barPx = 0; // the timeline's zoom: pixels per bar (0: the whole remix fits)
  double _dragBars = 0; // bars while a part's edge is dragged

  AppState get app => widget.app;

  @override
  void dispose() {
    _title.dispose();
    _titleFocus.dispose();
    super.dispose();
  }

  void _sync() {
    final a = app.arrangement;
    if (a == null) {
      final err = app.arrangementSummary?['error'];
      if (!_requested && err == null && !app.busy) {
        _requested = true;
        WidgetsBinding.instance.addPostFrameCallback((_) => app.loadArrangement());
      }
      if (!_dirty) {
        _arr = null;
        _from = null;
      }
      return;
    }
    _requested = false;
    if (!identical(a, _from) && !_dirty) {
      _from = a;
      _arr = jsonDecode(jsonEncode(a)) as Map<String, dynamic>;
      _open.clear();
      _gen++;
    }
  }

  void _changed({bool rebuilt = false}) => setState(() {
        _dirty = true;
        if (rebuilt) {
          _open.clear();
          _gen++;
        }
      });

  List<Map<String, dynamic>> get _sections =>
      [for (final s in (_arr?['sections'] as List? ?? const [])) (s as Map).cast<String, dynamic>()];

  Future<bool> _confirmRebuild() async {
    final custom = app.arrangementSummary?['custom'] == true;
    if (!custom && !_dirty) return true;
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Rebuild the structure?'),
        content: const Text('Your section and track edits are replaced by a fresh structure with these options.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Keep my edits')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Rebuild')),
        ],
      ),
    );
    return ok == true;
  }

  Future<void> _option(Map<String, dynamic> opts) async {
    if (!await _confirmRebuild()) return;
    setState(() => _dirty = false);
    await app.setOptions(opts);
  }

  @override
  Widget build(BuildContext context) {
    _sync();
    final summary = app.arrangementSummary;
    return PageBody(
      title: 'Remix',
      subtitle: 'How your remix goes: its options, then every part in order — rename, resize, move, add or remove '
          'parts, and change what each track plays.',
      actions: [
        if (_dirty) ...[
          TextButton(
            onPressed: () => setState(() {
              _dirty = false;
              _from = null;
              _sync();
            }),
            child: const Text('Discard'),
          ),
          const SizedBox(width: 8),
          FilledButton.icon(
            onPressed: app.busy ? null : _save,
            icon: const Icon(Icons.save),
            label: const Text('Save structure'),
          ),
        ],
      ],
      children: [
        _optionsCard(context, summary),
        _structureCard(context, summary),
      ],
    );
  }

  Future<void> _save() async {
    final a = _arr;
    if (a == null) return;
    a['title'] = _title.text.trim().isEmpty ? a['title'] : _title.text.trim();
    await app.saveArrangement(a);
    setState(() {
      _dirty = false;
      _from = null;
    });
  }

  // ── options ──
  Widget _optionsCard(BuildContext context, Map<String, dynamic>? summary) {
    final opts = (app.project['options'] as Map?)?.cast<String, dynamic>() ?? {};
    final progs = <String, String>{};
    for (final pr in ((app.patterns?['sections'] as Map?)?['progression'] as List? ?? const [])) {
      final m = (pr as Map).cast<String, dynamic>();
      progs['${m['text']}'] = '${m['name']}  (${m['text']})';
    }
    final prog = '${summary?['progression'] ?? opts['progression'] ?? '0 1 -2 1'}';
    if (!progs.containsKey(prog)) progs[prog] = 'Custom ($prog)';
    final title = '${summary?['title'] ?? ''}';
    if (!_dirty && _title.text != title && !_titleFocus.hasFocus) _title.text = title;
    final enabled = !app.busy && summary?['error'] == null;
    return SectionCard(
      title: 'Options',
      subtitle: 'Built on ${app.builtOn}. Changing an option rebuilds the structure.',
      child: Wrap(spacing: 16, runSpacing: 16, crossAxisAlignment: WrapCrossAlignment.center, children: [
        SizedBox(
          width: 340,
          child: TextField(
            controller: _title,
            focusNode: _titleFocus,
            enabled: enabled,
            decoration: InputDecoration(
              labelText: 'Title',
              suffixIcon: IconButton(
                tooltip: 'Use this title',
                icon: const Icon(Icons.check),
                onPressed: () => _option({'title': _title.text.trim()}),
              ),
            ),
            onSubmitted: (v) => _option({'title': v.trim()}),
          ),
        ),
        LabeledDropdown<String>(
          label: 'Pitching',
          width: 210,
          enabled: enabled,
          value: '${summary?['pitching'] ?? opts['pitching'] ?? 'normal'}',
          items: const {'classic': 'Classic (sampler)', 'normal': 'Normal', 'hard': 'Hard (layers)'},
          onChanged: (v) => _option({'pitching': v}),
        ),
        LabeledDropdown<String>(
          label: 'Polish',
          width: 190,
          enabled: enabled,
          value: '${summary?['polish'] ?? opts['polish'] ?? 'normal'}',
          items: const {'light': 'Light', 'normal': 'Normal', 'hard': 'Hard (OTT, pump)'},
          onChanged: (v) => _option({'polish': v}),
        ),
        LabeledDropdown<String>(
          label: 'Progression twist',
          width: 330,
          enabled: enabled,
          value: prog,
          items: progs,
          onChanged: (v) => _option({'progression': v}),
        ),
        _switch('Minor patterns', opts['minor'] == true, enabled, (v) => _option({'minor': v})),
        _switch('Pitched chorus', opts['chorus_pitch'] == true, enabled, (v) => _option({'chorus_pitch': v}),
            tip: 'The Chorus normally plays the main phrase as it is. On: tuned to the chords, with octave layers.'),
        if (summary?['custom'] == true)
          TextButton.icon(
            onPressed: enabled ? () => _option({}) : null,
            icon: const Icon(Icons.restart_alt),
            label: const Text('Back to the built structure'),
          ),
      ]),
    );
  }

  Widget _switch(String label, bool value, bool enabled, ValueChanged<bool> onChanged, {String? tip}) {
    final w = Row(mainAxisSize: MainAxisSize.min, children: [
      Switch(value: value, onChanged: enabled ? onChanged : null),
      const SizedBox(width: 6),
      Text(label),
    ]);
    return tip == null ? w : Tooltip(message: tip, child: w);
  }

  // ── structure: the parts on a timeline ──
  Widget _structureCard(BuildContext context, Map<String, dynamic>? summary) {
    final err = summary?['error'];
    if (err != null && _arr == null) {
      return SectionCard(
        title: 'Structure',
        child: EmptyState(
          icon: Icons.info_outline,
          title: 'No structure yet',
          message: '$err',
          action: OutlinedButton(onPressed: () => app.go(AppPage.base), child: const Text('Go to Base')),
        ),
      );
    }
    final a = _arr;
    if (a == null) {
      return const SectionCard(
        title: 'Structure',
        child: Padding(padding: EdgeInsets.all(24), child: Center(child: CircularProgressIndicator())),
      );
    }
    final secs = _sections;
    if (_sel >= secs.length) _sel = secs.isEmpty ? 0 : secs.length - 1;
    final bars = secs.fold<int>(0, (x, s) => x + _barsOf(s));
    final bpm = (a['bpm'] as num?)?.toDouble() ?? 140;
    final seconds = bars * 4 * 60 / bpm;
    return SectionCard(
      title: 'Structure',
      subtitle: '${bpm.toStringAsFixed(bpm == bpm.roundToDouble() ? 0 : 1)} BPM · $bars bars · ${fmtDuration(seconds)} · '
          'key ${a['key']}${_dirty ? ' · not saved yet' : ''}',
      trailing: summary?['custom'] == true ? const Pill('edited', icon: Icons.edit) : null,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('Drag a part to move it, drag its right edge to make it longer or shorter, tap it to change it.',
            style: Theme.of(context)
                .textTheme
                .bodySmall
                ?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant)),
        const SizedBox(height: 10),
        _timeline(context, secs, bpm),
        const SizedBox(height: 10),
        _palette(context),
        const SizedBox(height: 14),
        if (secs.isNotEmpty) _partEditor(context, _sel, secs[_sel]),
      ]),
    );
  }

  static int _barsOf(Map<String, dynamic> s) => (s['bars'] as num?)?.toInt() ?? 1;

  static const _minBlock = 52.0; // a part on the timeline is never narrower than this (px)

  static const _defaultBars = {
    'intro': 4, 'intro_hits': 2, 'chorus': 8, 'dundundenden': 8, 'epicness': 8, 'chords': 4, 'awesomeness1': 4, //
    'awesomeness2': 4, 'madness': 8, 'execution': 8, 'chorus_final': 8, 'ending': 2,
  };

  /// A new part after the one shown (an ending stays last).
  Future<void> _addSection(String kind) async {
    final sec = await app.newSection(kind, _defaultBars[kind] ?? 8);
    if (sec == null || _arr == null) return;
    final list = _arr!['sections'] as List;
    var at = list.isEmpty ? 0 : _sel + 1;
    if (kind != 'ending' && at == list.length && list.isNotEmpty && (list.last as Map)['kind'] == 'ending') {
      at = list.length - 1;
    }
    setState(() {
      list.insert(at, sec);
      _sel = at;
      _gen++;
      _open.clear();
      _dirty = true;
    });
  }

  Widget _timeline(BuildContext context, List<Map<String, dynamic>> secs, double bpm) {
    final cs = Theme.of(context).colorScheme;
    final list = _arr!['sections'] as List;
    final total = secs.fold<int>(0, (x, s) => x + _barsOf(s));
    return LayoutBuilder(builder: (context, box) {
      // To fit the whole remix: short parts keep a readable width, the others share what is left.
      final room = box.maxWidth - 6.0 * secs.length;
      var fit = total == 0 ? 24.0 : room / total;
      for (var k = 0; k < 3 && total > 0; k++) {
        final small = secs.where((s) => _barsOf(s) * fit < _minBlock).toList();
        final rest = total - small.fold<int>(0, (x, s) => x + _barsOf(s));
        if (rest <= 0) break;
        fit = (room - small.length * _minBlock) / rest;
      }
      final px = (_barPx > 0 ? _barPx : fit).clamp(4.0, 90.0).toDouble();
      final starts = <int>[];
      var bar = 0;
      for (final s in secs) {
        starts.add(bar);
        bar += _barsOf(s);
      }
      return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        SizedBox(
          height: 96,
          child: ReorderableListView.builder(
            scrollDirection: Axis.horizontal,
            buildDefaultDragHandles: false,
            itemCount: secs.length,
            proxyDecorator: (child, i, animation) => Material(color: Colors.transparent, elevation: 8, child: child),
            onReorderItem: (from, to) {
              if (to == from) return;
              list.insert(to, list.removeAt(from));
              _sel = to;
              _changed(rebuilt: true);
            },
            itemBuilder: (context, i) =>
                _block(context, i, secs[i], px, starts[i], bpm, key: ValueKey('part-$_gen-$i')),
          ),
        ),
        Row(children: [
          IconButton(
            tooltip: 'Zoom out',
            icon: const Icon(Icons.zoom_out),
            onPressed: () => setState(() => _barPx = max(4, px / 1.5)),
          ),
          IconButton(
            tooltip: 'Zoom in',
            icon: const Icon(Icons.zoom_in),
            onPressed: () => setState(() => _barPx = min(90, px * 1.5)),
          ),
          if (_barPx > 0)
            TextButton(onPressed: () => setState(() => _barPx = 0), child: const Text('Fit the whole remix')),
          const Spacer(),
          Text('${secs.length} parts', style: TextStyle(color: cs.onSurfaceVariant)),
        ]),
      ]);
    });
  }

  /// A part on the timeline: as wide as it is long, its colour, name, length, picture and start.
  Widget _block(BuildContext context, int i, Map<String, dynamic> s, double px, int startBar, double bpm,
      {required Key key}) {
    final cs = Theme.of(context).colorScheme;
    final kind = '${s['kind']}';
    final bars = _barsOf(s);
    final selected = i == _sel;
    final color = partColor(kind);
    final on = onPartColor(kind);
    final width = max(_minBlock, bars * px);
    final platform = Theme.of(context).platform;
    final touch = platform == TargetPlatform.android || platform == TargetPlatform.iOS;
    final body = GestureDetector(
      onTap: () => setState(() => _sel = i),
      child: Tooltip(
        message: '${_name(s)} · $bars bars · from ${fmtDuration(startBar * 4 * 60 / bpm)}',
        waitDuration: const Duration(milliseconds: 600),
        child: Container(
          width: width - 12,
          padding: const EdgeInsets.fromLTRB(8, 6, 4, 6),
          decoration: BoxDecoration(
            color: color,
            borderRadius: const BorderRadius.horizontal(left: Radius.circular(8)),
            border: Border.all(color: selected ? cs.onSurface : Colors.transparent, width: 3),
          ),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(_name(s),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(color: on, fontWeight: FontWeight.w700, fontSize: 12.5)),
            Text('$bars bar${bars == 1 ? '' : 's'}',
                maxLines: 1,
                overflow: TextOverflow.clip,
                style: TextStyle(color: on.withValues(alpha: 0.85), fontSize: 11)),
            const Spacer(),
            Row(children: [
              Icon(_layoutIcons['${s['layout']}'] ?? Icons.dashboard_outlined, size: 14, color: on),
              const SizedBox(width: 4),
              Flexible(
                child: Text(fmtDuration(startBar * 4 * 60 / bpm),
                    maxLines: 1, overflow: TextOverflow.clip, style: TextStyle(color: on, fontSize: 10.5)),
              ),
            ]),
          ]),
        ),
      ),
    );
    // Its right edge: drag it to make the part longer or shorter, a bar at a time.
    final edge = MouseRegion(
      cursor: SystemMouseCursors.resizeLeftRight,
      child: GestureDetector(
        behavior: HitTestBehavior.opaque,
        onHorizontalDragStart: (_) => _dragBars = bars.toDouble(),
        onHorizontalDragUpdate: (d) {
          _dragBars += d.delta.dx / px;
          final nb = _dragBars.round().clamp(1, 64);
          if (nb != _barsOf(s)) {
            s['bars'] = nb;
            _sel = i;
            _changed();
          }
        },
        child: Tooltip(
          message: 'Drag to change its length',
          waitDuration: const Duration(milliseconds: 600),
          child: Container(
            width: 12,
            decoration: BoxDecoration(
              color: Color.lerp(color, Colors.black, 0.3),
              borderRadius: const BorderRadius.horizontal(right: Radius.circular(8)),
            ),
            alignment: Alignment.center,
            child: Container(width: 2, height: 30, color: on.withValues(alpha: 0.7)),
          ),
        ),
      ),
    );
    return Padding(
      key: key,
      padding: const EdgeInsets.only(right: 6),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        touch
            ? ReorderableDelayedDragStartListener(index: i, child: body)
            : ReorderableDragStartListener(index: i, child: body),
        edge,
      ]),
    );
  }

  /// The parts one can add: a tap puts one after the part shown.
  Widget _palette(BuildContext context) {
    return Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
      const Text('Add a part:'),
      for (final k in _addable)
        ActionChip(
          avatar: CircleAvatar(backgroundColor: partColor(k), radius: 7),
          label: Text(partNames[k] ?? k),
          tooltip: 'Add ${partNames[k] ?? k} after the part shown',
          onPressed: app.busy ? null : () => _addSection(k),
        ),
    ]);
  }

  static String _name(Map<String, dynamic> s) {
    final n = '${s['name'] ?? ''}'.trim();
    return n.isNotEmpty ? n : (partNames['${s['kind']}'] ?? '${s['kind']}');
  }

  /// The part tapped on the timeline: its name, length, place, picture and tracks.
  Widget _partEditor(BuildContext context, int i, Map<String, dynamic> s) {
    final cs = Theme.of(context).colorScheme;
    final kind = '${s['kind']}';
    final open = _open.contains(i);
    final list = _arr!['sections'] as List;
    final tracks = [for (final t in (s['tracks'] as List? ?? const [])) (t as Map).cast<String, dynamic>()];
    final layout = '${s['layout'] ?? 'grid3'}';
    return Container(
      padding: const EdgeInsets.fromLTRB(14, 12, 10, 12),
      decoration: BoxDecoration(
        color: cs.surfaceContainer,
        borderRadius: BorderRadius.circular(12),
        border: Border(left: BorderSide(color: partColor(kind), width: 6)),
      ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Wrap(spacing: 10, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          SizedBox(
            width: 220,
            child: _InlineField(
              key: ValueKey('name-$_gen-$i'),
              initial: _name(s),
              label: 'Part ${i + 1} of ${list.length}',
              onChanged: (v) {
                s['name'] = v;
                _changed();
              },
            ),
          ),
          Pill(partNames[kind] ?? kind, color: partColor(kind)),
          _Stepper(
            label: 'bars',
            value: _barsOf(s),
            min: 1,
            max: 64,
            onChanged: (v) {
              s['bars'] = v;
              _changed();
            },
          ),
          Row(mainAxisSize: MainAxisSize.min, children: [
            IconButton(
              tooltip: 'Move earlier',
              icon: const Icon(Icons.arrow_back),
              onPressed: i == 0
                  ? null
                  : () {
                      list.insert(i - 1, list.removeAt(i));
                      _sel = i - 1;
                      _changed(rebuilt: true);
                    },
            ),
            IconButton(
              tooltip: 'Move later',
              icon: const Icon(Icons.arrow_forward),
              onPressed: i == list.length - 1
                  ? null
                  : () {
                      list.insert(i + 1, list.removeAt(i));
                      _sel = i + 1;
                      _changed(rebuilt: true);
                    },
            ),
            IconButton(
              tooltip: 'Duplicate',
              icon: const Icon(Icons.copy_all_outlined),
              onPressed: () {
                list.insert(i + 1, jsonDecode(jsonEncode(s)));
                _sel = i + 1;
                _changed(rebuilt: true);
              },
            ),
            IconButton(
              tooltip: 'Remove',
              icon: const Icon(Icons.delete_outline),
              onPressed: list.length <= 1
                  ? null
                  : () async {
                      final ok = await showDialog<bool>(
                        context: context,
                        builder: (c) => AlertDialog(
                          title: Text('Remove ${_name(s)}?'),
                          actions: [
                            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Cancel')),
                            FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Remove')),
                          ],
                        ),
                      );
                      if (ok != true) return;
                      list.removeAt(i);
                      _sel = max(0, i - 1);
                      _changed(rebuilt: true);
                    },
            ),
          ]),
        ]),
        const SizedBox(height: 12),
        Text('Picture', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 6),
        Wrap(spacing: 10, runSpacing: 10, children: [
          for (final e in _layouts.entries)
            _LayoutChoice(
              layout: e.key,
              label: e.value,
              selected: layout == e.key,
              onTap: () {
                s['layout'] = e.key;
                _changed();
              },
            ),
        ]),
        const SizedBox(height: 8),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => setState(() => open ? _open.remove(i) : _open.add(i)),
            icon: Icon(open ? Icons.expand_less : Icons.expand_more),
            label: Text('Tracks (${tracks.length})'),
          ),
        ),
        if (open) ...[for (var j = 0; j < tracks.length; j++) _trackRow(context, tracks[j], 'pt-$_gen-$i-$j')],
      ]),
    );
  }

  List<String> get _sampleIds {
    final list = app.bank?['samples'] as List?;
    if (list == null) return _defaultSamples;
    return [for (final s in list) '${(s as Map)['id']}'];
  }

  Widget _trackRow(BuildContext context, Map<String, dynamic> t, String fieldKey) {
    final cs = Theme.of(context).colorScheme;
    final muted = t['muted'] == true;
    final pattern = '${t['pattern'] ?? ''}';
    final slots = (t['slots'] as Map?) ?? const {};
    final voices = (t['voice_samples'] as List?) ?? const [];
    final kind = '${t['kind']}';
    final samples = _sampleIds;
    final sample = '${t['sample'] ?? ''}';
    return Opacity(
      opacity: muted ? 0.55 : 1,
      child: Container(
        margin: const EdgeInsets.only(top: 8),
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: cs.surfaceContainerHigh,
          borderRadius: BorderRadius.circular(8),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Wrap(spacing: 10, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            SizedBox(
              width: 150,
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text('${t['id']}', style: const TextStyle(fontWeight: FontWeight.w600)),
                Text('$kind${'${t['follow'] ?? ''}'.isNotEmpty ? ' · follows ${t['follow']}' : ''}',
                    style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
              ]),
            ),
            if (pattern.isNotEmpty || kind != 'drum')
              OutlinedButton.icon(
                onPressed: () async {
                  final v = await _pickPattern(context, t);
                  if (v == null) return;
                  t['pattern'] = v;
                  if (v.startsWith('text:') || (!v.startsWith('drum:') && !v.startsWith('bass:'))) t['mode'] = 'auto';
                  _changed();
                },
                icon: const Icon(Icons.piano, size: 18),
                label: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 260),
                  child: Text(_patternName(pattern), overflow: TextOverflow.ellipsis),
                ),
              ),
            if (slots.isNotEmpty)
              Pill('plays ${slots.entries.map((e) => '${e.key}→${e.value is Map ? (e.value as Map)['sample'] : e.value}').join(', ')}',
                  icon: Icons.grid_view)
            else
              LabeledDropdown<String>(
                label: 'Sample',
                width: 180,
                value: sample,
                items: {for (final id in {...samples, if (sample.isNotEmpty) sample}) id: id},
                onChanged: (v) {
                  t['sample'] = v;
                  if (voices.isNotEmpty) t['voice_samples'] = [];
                  _changed();
                },
              ),
          ]),
          if (voices.isNotEmpty && slots.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 6),
              child: Text('One pitch per line of the pattern: ${voices.join(' · ')} — picking a sample plays every line with it.',
                  style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
            ),
          if (pattern.startsWith('text:'))
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: _InlineField(
                key: ValueKey(fieldKey),
                initial: pattern.substring(5),
                label: 'Pattern (wiki notation)',
                maxLines: 3,
                onChanged: (v) {
                  t['pattern'] = 'text:$v';
                  _changed();
                },
              ),
            ),
          const SizedBox(height: 8),
          Wrap(spacing: 14, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
            _Stepper(
              label: 'dB',
              value: ((t['gain_db'] as num?) ?? 0).round(),
              min: -30,
              max: 12,
              onChanged: (v) {
                t['gain_db'] = v.toDouble();
                _changed();
              },
            ),
            _Stepper(
              label: 'octave',
              value: ((t['octave'] as num?) ?? 0).toInt(),
              min: -3,
              max: 3,
              signed: true,
              onChanged: (v) {
                t['octave'] = v;
                _changed();
              },
            ),
            _check('Crisp', t['crisp'] == true, (v) {
              t['crisp'] = v;
              _changed();
            }),
            _check('Mute', muted, (v) {
              t['muted'] = v;
              _changed();
            }),
          ]),
        ]),
      ),
    );
  }

  Widget _check(String label, bool v, ValueChanged<bool> on) => Row(mainAxisSize: MainAxisSize.min, children: [
        Checkbox(value: v, onChanged: (x) => on(x ?? false)),
        Text(label),
      ]);

  static String _bars(dynamic v) {
    final d = (v as num?)?.toDouble() ?? 0;
    final txt = d == d.roundToDouble() ? d.toStringAsFixed(0) : d.toStringAsFixed(2).replaceFirst(RegExp(r'0+$'), '');
    return '$txt bar${d == 1 ? '' : 's'}';
  }

  String _patternName(String id) {
    if (id.isEmpty) return '(follows another track)';
    if (id.startsWith('text:')) return 'Custom pattern';
    if (id.startsWith('drum:')) {
      final parts = id.split(':');
      return parts.length >= 3 ? 'Drums: ${parts[1]} · ${parts[2]}' : id;
    }
    if (id.startsWith('bass:')) return 'Bass: ${id.substring(5)}';
    final secs = (app.patterns?['sections'] as Map?) ?? const {};
    for (final list in secs.values) {
      for (final p in (list as List)) {
        if ((p as Map)['id'] == id) return '${p['name']}';
      }
    }
    return id;
  }

  Future<String?> _pickPattern(BuildContext context, Map<String, dynamic> t) {
    final cat = app.patterns ?? const {};
    final groups = <(String, List<(String, String, String)>)>[]; // (title, [(value, name, detail)])
    final kind = '${t['kind']}';
    if (kind == 'drum') {
      final drums = (cat['drums'] as Map?) ?? const {};
      groups.add(('Drum grooves', [
        for (final g in drums.entries)
          for (final part in (g.value as Map).entries)
            if (part.value != null && '${part.value}'.isNotEmpty) ('drum:${g.key}:${part.key}', '${g.key} · ${part.key}', ''),
      ]));
    }
    if (kind == 'bass') {
      final bass = (cat['bass'] as Map?) ?? const {};
      groups.add(('Bass grooves', [for (final g in bass.keys) ('bass:$g', '$g', '')]));
    }
    final secs = (cat['sections'] as Map?) ?? const {};
    final titles = (cat['titles'] as Map?) ?? const {};
    for (final sec in _trackSections[kind] ?? const <String>[]) {
      final list = secs[sec] as List?;
      if (list == null || list.isEmpty) continue;
      groups.add(('${titles[sec] ?? sec}', [
        for (final p in list)
          ('${(p as Map)['id']}', '${p['name']}', '${_bars(p['bars'])}${'${p['credit'] ?? ''}'.isNotEmpty ? ' · ${p['credit']}' : ''}'),
      ]));
    }
    groups.add(('Your own', [('text:${'${t['pattern']}'.startsWith('text:') ? '${t['pattern']}'.substring(5) : ''}', 'Custom pattern…', 'type it in wiki notation')]));
    return showDialog<String>(
      context: context,
      builder: (context) => _PatternDialog(groups: groups, current: '${t['pattern'] ?? ''}'),
    );
  }
}

/// A picture a part can have, drawn as its boxes; tap to use it.
class _LayoutChoice extends StatelessWidget {
  const _LayoutChoice({required this.layout, required this.label, required this.selected, required this.onTap});

  final String layout;
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Tooltip(
      message: label,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(10),
        child: Container(
          width: 118,
          padding: const EdgeInsets.all(6),
          decoration: BoxDecoration(
            color: selected ? cs.primary.withValues(alpha: 0.12) : cs.surfaceContainerHigh,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: selected ? cs.primary : cs.outlineVariant, width: selected ? 2 : 1),
          ),
          child: Column(children: [
            AspectRatio(
              aspectRatio: 16 / 9,
              child: CustomPaint(
                painter: _LayoutPainter(
                  boxes: _layoutBoxes(layout),
                  main: layout == 'main' || layout == 'full',
                  fill: selected ? cs.primary : cs.onSurfaceVariant,
                  back: Colors.black,
                ),
              ),
            ),
            const SizedBox(height: 4),
            Text(label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 11.5, fontWeight: selected ? FontWeight.w700 : FontWeight.w500)),
          ]),
        ),
      ),
    );
  }
}

class _LayoutPainter extends CustomPainter {
  _LayoutPainter({required this.boxes, required this.main, required this.fill, required this.back});

  final List<Rect> boxes;
  final bool main; // the first box is the main phrase's (drawn stronger)
  final Color fill;
  final Color back;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRRect(RRect.fromRectAndRadius(Offset.zero & size, const Radius.circular(4)), Paint()..color = back);
    for (var i = 0; i < boxes.length; i++) {
      final b = boxes[i];
      final rect = Rect.fromLTWH(b.left * size.width + 1, b.top * size.height + 1, b.width * size.width - 2,
          b.height * size.height - 2);
      canvas.drawRRect(RRect.fromRectAndRadius(rect, const Radius.circular(2)),
          Paint()..color = fill.withValues(alpha: main && i == 0 ? 0.95 : 0.55));
    }
  }

  @override
  bool shouldRepaint(covariant _LayoutPainter old) => old.fill != fill || old.boxes.length != boxes.length;
}

class _PatternDialog extends StatefulWidget {
  const _PatternDialog({required this.groups, required this.current});

  final List<(String, List<(String, String, String)>)> groups;
  final String current;

  @override
  State<_PatternDialog> createState() => _PatternDialogState();
}

class _PatternDialogState extends State<_PatternDialog> {
  String _q = '';

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final q = _q.toLowerCase();
    final items = <Widget>[];
    for (final (title, list) in widget.groups) {
      final hits = [for (final e in list) if (q.isEmpty || e.$2.toLowerCase().contains(q) || title.toLowerCase().contains(q)) e];
      if (hits.isEmpty) continue;
      items.add(Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 16, 4),
        child: Text(title, style: TextStyle(color: cs.primary, fontWeight: FontWeight.w700)),
      ));
      for (final (value, name, detail) in hits) {
        final selected = value == widget.current || (value.startsWith('text:') && widget.current.startsWith('text:'));
        items.add(ListTile(
          dense: true,
          selected: selected,
          title: Text(name),
          subtitle: detail.isEmpty ? null : Text(detail),
          trailing: selected ? const Icon(Icons.check) : null,
          onTap: () => Navigator.pop(context, value),
        ));
      }
    }
    return Dialog(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520, maxHeight: 640),
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: TextField(
              autofocus: true,
              decoration: const InputDecoration(prefixIcon: Icon(Icons.search), labelText: 'Find a pattern'),
              onChanged: (v) => setState(() => _q = v),
            ),
          ),
          Expanded(child: ListView(children: items)),
          Padding(
            padding: const EdgeInsets.all(8),
            child: Align(
              alignment: Alignment.centerRight,
              child: TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
            ),
          ),
        ]),
      ),
    );
  }
}

/// A text field that reports every change and keeps its own controller.
class _InlineField extends StatefulWidget {
  const _InlineField({super.key, required this.initial, required this.onChanged, this.label, this.maxLines = 1});

  final String initial;
  final ValueChanged<String> onChanged;
  final String? label;
  final int maxLines;

  @override
  State<_InlineField> createState() => _InlineFieldState();
}

class _InlineFieldState extends State<_InlineField> {
  late final TextEditingController _c = TextEditingController(text: widget.initial);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => TextField(
        controller: _c,
        maxLines: widget.maxLines,
        minLines: 1,
        style: widget.maxLines > 1 ? const TextStyle(fontFamily: 'monospace') : null,
        decoration: InputDecoration(labelText: widget.label),
        onChanged: widget.onChanged,
      );
}

/// − value + for a small whole number.
class _Stepper extends StatelessWidget {
  const _Stepper({required this.label, required this.value, required this.min, required this.max, required this.onChanged,
      this.signed = false});

  final String label;
  final int value;
  final int min;
  final int max;
  final bool signed;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Container(
      decoration: BoxDecoration(
        border: Border.all(color: cs.outlineVariant),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        IconButton(
          visualDensity: VisualDensity.compact,
          icon: const Icon(Icons.remove, size: 18),
          onPressed: value > min ? () => onChanged(value - 1) : null,
        ),
        SizedBox(
          width: 64,
          child: Text(
              '${signed && value > 0 ? '+' : ''}$value '
              '${value == 1 && label == 'bars' ? 'bar' : label}',
              textAlign: TextAlign.center),
        ),
        IconButton(
          visualDensity: VisualDensity.compact,
          icon: const Icon(Icons.add, size: 18),
          onPressed: value < max ? () => onChanged(value + 1) : null,
        ),
      ]),
    );
  }
}
