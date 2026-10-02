// The block editor: a track's pattern as blocks on a grid of 16ths, instead of the wiki's notation.  A row per
// note — pitches: the semitones from the key; drums, the chorus, words: what each slot plays — and a column per
// 16th.  Tap a square to put a block there, tap a block to take it away; with a mouse, drag to draw a longer one.
// What is drawn is written back as the notation (shown under the grid), so the pattern plays exactly as drawn.

import 'dart:async';
import 'dart:math';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import '../../state/app_state.dart';
import 'common.dart';

/// One block: from [start] for [dur] 16ths, at [value] (semitones, or the slot), on line [voice] (notes that
/// sound together are on lines of their own).
class BlockNote {
  BlockNote(this.start, this.dur, this.value, {this.voice = 0, this.sharp = 0});

  factory BlockNote.fromJson(Map<String, dynamic> m) => BlockNote(
        (m['start'] as num).toDouble(),
        (m['dur'] as num).toDouble(),
        (m['value'] as num).toInt(),
        voice: (m['voice'] as num?)?.toInt() ?? 0,
        sharp: (m['sharp'] as num?)?.toInt() ?? 0,
      );

  double start;
  double dur;
  final int value;
  int voice;
  final int sharp;

  double get end => start + dur;

  BlockNote copy() => BlockNote(start, dur, value, voice: voice, sharp: sharp);

  Map<String, dynamic> toJson() => {'start': start, 'dur': dur, 'value': value, 'voice': voice, 'sharp': sharp};
}

/// Opens the block editor for [track] (a track of part [section]) full screen; true when the track was changed
/// (its pattern is then the notation of what was drawn).
Future<bool> editPatternBlocks(BuildContext context, AppState app, Map<String, dynamic> track, int section) async {
  final view = await app.patternBlocks(track);
  if (view == null || !context.mounted) return false;
  final changed = await Navigator.of(context).push<bool>(MaterialPageRoute(
    fullscreenDialog: true,
    builder: (_) => PatternBlocksPage(app: app, track: track, view: view, section: section),
  ));
  return changed == true;
}

const _noteNames = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const _flats = {'Db': 'C#', 'Eb': 'D#', 'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#', 'Cb': 'B', 'Fb': 'E'};

/// The pitch class of a key's root ("D", "F#", "Bb minor" …).
int keyRoot(String key) {
  final k = key.trim().split(RegExp(r'\s')).first;
  final i = _noteNames.indexOf(_flats[k] ?? k);
  return i < 0 ? 2 : i;
}

/// A row's name: the note [value] semitones from the key's root, and the octave it is in counted from the
/// root's (in D: 0 → D, 7 → A, 12 → D+1, -5 → A-1).
String noteLabel(int value, int root) {
  final octave = (value / 12).floor();
  return '${_noteNames[(root + value) % 12]}${octave > 0 ? '+$octave' : octave < 0 ? '$octave' : ''}';
}

/// What a new block is long (16ths).
const _lengths = {1: '1/16', 2: '1/8', 3: '3/16', 4: '1/4', 8: '1/2', 16: '1 bar'};

class PatternBlocksPage extends StatefulWidget {
  const PatternBlocksPage({super.key, required this.app, required this.track, required this.view, required this.section});

  final AppState app;
  final Map<String, dynamic> track;
  final Map<String, dynamic> view;
  final int section;

  @override
  State<PatternBlocksPage> createState() => _PatternBlocksPageState();
}

class _PatternBlocksPageState extends State<PatternBlocksPage> {
  late List<BlockNote> notes;
  late final String mode; // semitone | index
  late double loop; // the pattern's loop (16ths), after its lead-in
  late final double pickup; // 16ths written before its downbeat
  late final String over;
  late final bool once; // a MIDI base's notes: played once, as they are
  late final Map<String, String> slots;
  late final List<int> rows; // the values, top row first
  double res = 1; // a column: a 16th (0.5: a 32nd)
  int newLength = 1; // (16ths)
  double cellW = 26;
  static const cellH = 24.0;
  static const header = 22.0;
  double get labelW => mode == 'index' ? 132 : 64;
  final List<List<BlockNote>> _undo = [];
  bool changed = false;
  String text = '';
  Timer? _textTimer;
  final _vertical = ScrollController();
  final _horizontal = ScrollController();
  final _bars = ScrollController(); // the bar numbers, kept over the grid while it scrolls
  // (a mouse draws: the block being drawn, or the one pressed)
  BlockNote? _drawing;
  BlockNote? _pressed;
  bool _moved = false;

  AppState get app => widget.app;

  double get total => pickup + loop;

  @override
  void initState() {
    super.initState();
    final v = widget.view;
    notes = [for (final n in (v['notes'] as List? ?? const [])) BlockNote.fromJson((n as Map).cast<String, dynamic>())];
    mode = '${v['mode']}' == 'index' ? 'index' : 'semitone';
    pickup = (v['pickup'] as num?)?.toDouble() ?? 0;
    loop = (v['loop'] as num?)?.toDouble() ?? 16;
    over = '${v['over'] ?? ''}';
    once = v['once'] == true;
    slots = ((v['slots'] as Map?) ?? const {}).map((k, val) => MapEntry('$k', '$val'));
    if (notes.any((n) => n.start % 1 != 0 || n.dur % 1 != 0)) res = 0.5;
    final values = notes.map((n) => n.value);
    if (mode == 'index') {
      final used = {...slots.keys.map(int.tryParse).whereType<int>(), ...values};
      final hi = max(3, used.isEmpty ? 3 : used.reduce(max));
      final lo = min(1, used.isEmpty ? 1 : used.reduce(min));
      rows = [for (var x = lo; x <= min(hi, 9); x++) x];
    } else {
      final lo = max(-36, min(-12, values.isEmpty ? 0 : values.reduce(min) - 2));
      final hi = min(36, max(19, values.isEmpty ? 0 : values.reduce(max) + 2));
      rows = [for (var x = hi; x >= lo; x--) x];
    }
    // Start at the pattern's highest note (pitches) — or the top.
    final top = values.isEmpty ? 0 : (mode == 'index' ? values.reduce(min) : values.reduce(max));
    final at = max(0, rows.indexOf(top) - 2);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_vertical.hasClients) {
        _vertical.jumpTo(min(at * cellH, _vertical.position.maxScrollExtent));
      }
    });
    _horizontal.addListener(() {
      if (_bars.hasClients && _bars.offset != _horizontal.offset) _bars.jumpTo(_horizontal.offset);
    });
    _refreshText(now: true);
  }

  @override
  void dispose() {
    _textTimer?.cancel();
    _vertical.dispose();
    _horizontal.dispose();
    _bars.dispose();
    super.dispose();
  }

  // ── what is drawn ──

  String _rowLabel(int value) {
    if (mode == 'index') {
      final s = slots['$value'];
      return s == null ? 'slot $value' : '$value · $s';
    }
    return noteLabel(value, keyRoot(app.key));
  }

  BlockNote? _noteAt(int value, double step) {
    for (final n in notes.reversed) {
      if (n.value == value && n.start <= step + 1e-9 && step < n.end - 1e-9) return n;
    }
    return null;
  }

  /// The first line with nothing playing from [start] for [dur].
  int _freeVoice(double start, double dur, [BlockNote? except]) {
    var v = 0;
    while (notes.any((n) => !identical(n, except) && n.voice == v && n.start < start + dur - 1e-9 &&
        start < n.end - 1e-9)) {
      v++;
    }
    return v;
  }

  void _remember() {
    _undo.add([for (final n in notes) n.copy()]);
    if (_undo.length > 100) _undo.removeAt(0);
  }

  void _edited() {
    changed = true;
    setState(() {});
    _refreshText();
  }

  void _add(int value, double step, double length) {
    final dur = min(length, total - step);
    if (dur <= 0) return;
    _remember();
    notes.add(BlockNote(step, dur, value, voice: _freeVoice(step, dur)));
    _edited();
  }

  void _remove(BlockNote n) {
    _remember();
    notes.remove(n);
    _edited();
  }

  /// (row value, step) under a point of the grid; null over the bar numbers.
  (int, double)? _cellAt(Offset p) {
    final r = (p.dy / cellH).floor();
    final c = (p.dx / cellW).floor();
    if (r < 0 || r >= rows.length || c < 0) return null;
    final step = c * res;
    if (step >= total - 1e-9) return null;
    return (rows[r], step);
  }

  void _tap(Offset p) {
    final cell = _cellAt(p);
    if (cell == null) return;
    final hit = _noteAt(cell.$1, cell.$2);
    if (hit != null) {
      _remove(hit);
    } else {
      _add(cell.$1, cell.$2, newLength.toDouble());
    }
  }

  // A mouse: press on a square and drag to draw a block as long as the drag; press on a block and let go to
  // take it away.
  void _mouseDown(PointerDownEvent e) {
    if (e.kind != PointerDeviceKind.mouse || e.buttons != kPrimaryMouseButton) return;
    final cell = _cellAt(e.localPosition);
    if (cell == null) return;
    _moved = false;
    final hit = _noteAt(cell.$1, cell.$2);
    if (hit != null) {
      _pressed = hit;
      return;
    }
    _remember();
    final dur = min(newLength.toDouble(), total - cell.$2);
    final n = BlockNote(cell.$2, dur, cell.$1, voice: _freeVoice(cell.$2, dur));
    notes.add(n);
    _drawing = n;
    setState(() {});
  }

  void _mouseMove(PointerMoveEvent e) {
    final n = _drawing;
    if (n == null) {
      if (_pressed != null) _moved = true;
      return;
    }
    final c = (e.localPosition.dx / cellW).floor();
    final end = min(total, max(n.start + res, (c + 1) * res));
    if ((end - n.end).abs() < 1e-9) return;
    _moved = true;
    n.dur = end - n.start;
    n.voice = _freeVoice(n.start, n.dur, n);
    setState(() {});
  }

  void _mouseUp(PointerUpEvent e) {
    if (_drawing != null) {
      _drawing = null;
      _edited();
    } else if (_pressed != null && !_moved) {
      _remove(_pressed!);
    }
    _pressed = null;
  }

  // ── the pattern ──

  void _setBars(int bars) {
    _remember();
    loop = bars * 16.0;
    notes.removeWhere((n) => n.start >= total - 1e-9);
    for (final n in notes) {
      if (n.end > total) n.dur = total - n.start;
    }
    _edited();
  }

  List<Map<String, dynamic>> get _json => [for (final n in notes) n.toJson()];

  void _refreshText({bool now = false}) {
    if (once) return;
    _textTimer?.cancel();
    _textTimer = Timer(now ? Duration.zero : const Duration(milliseconds: 250), () async {
      final t = await app.writePattern(_json, mode, total);
      if (mounted && t != null) setState(() => text = t);
    });
  }

  /// The track as drawn (its pattern written out as the notation, or its notes).
  Future<Map<String, dynamic>?> _drawnTrack() async {
    final t = Map<String, dynamic>.from(widget.track);
    if (once) {
      final sorted = [...notes]..sort((a, b) => a.start.compareTo(b.start));
      t['notes'] = [for (final n in sorted) [n.start, n.dur, n.value, n.voice]];
      return t;
    }
    final written = await app.writePattern(_json, mode, total);
    if (written == null) return null;
    t['pattern'] = 'text:$written';
    t['mode'] = mode;
    t['loop'] = loop;
    t['pickup'] = pickup;
    t['over'] = over;
    return t;
  }

  Future<void> _listen() async {
    final t = await _drawnTrack();
    if (t == null) return;
    final audio = await app.listenPattern(t, widget.section);
    if (audio != null) await Players.playSound(audio, tag: 'pattern');
  }

  Future<void> _done() async {
    if (!changed) {
      Navigator.pop(context, false);
      return;
    }
    final t = await _drawnTrack();
    if (t == null || !mounted) return;
    widget.track
      ..clear()
      ..addAll(t);
    Navigator.pop(context, true);
  }

  Future<void> _close() async {
    if (!changed) {
      Navigator.pop(context, false);
      return;
    }
    final leave = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('Leave without saving?'),
        content: const Text('The blocks you changed are not kept.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Keep editing')),
          FilledButton(onPressed: () => Navigator.pop(c, true), child: const Text('Leave')),
        ],
      ),
    );
    if (leave == true && mounted) Navigator.pop(context, false);
  }

  // ── the page ──

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final cols = (total / res).ceil();
    final busy = app.busy;
    final barStyle = Theme.of(context).textTheme.labelSmall!.copyWith(
        fontWeight: FontWeight.w700, color: cs.onSurfaceVariant);
    return PopScope(
      canPop: !changed,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop) _close();
      },
      child: Scaffold(
        appBar: AppBar(
          leading: IconButton(icon: const Icon(Icons.close), tooltip: 'Close', onPressed: _close),
          title: Text('${widget.track['id']} · blocks', overflow: TextOverflow.ellipsis),
          actions: [
            IconButton(
              tooltip: 'Undo',
              onPressed: _undo.isEmpty
                  ? null
                  : () {
                      notes = _undo.removeLast();
                      _edited();
                    },
              icon: const Icon(Icons.undo),
            ),
            IconButton(
                tooltip: 'Listen', onPressed: busy ? null : _listen, icon: const Icon(Icons.play_circle_outline)),
            Padding(
              padding: const EdgeInsets.only(right: 10, left: 4),
              child: FilledButton.icon(onPressed: busy ? null : _done, icon: const Icon(Icons.check), label: const Text('Done')),
            ),
          ],
        ),
        body: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 8, 12, 6),
            child: Wrap(spacing: 12, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
              if (!once)
                LabeledDropdown<int>(
                  label: 'Bars',
                  width: 110,
                  value: max(1, (loop / 16).round()),
                  items: {for (final b in ({1, 2, 4, 8, max(1, (loop / 16).round())}.toList()..sort())) b: '$b'},
                  onChanged: _setBars,
                ),
              LabeledDropdown<int>(
                label: 'New block',
                width: 130,
                value: newLength,
                items: {for (final e in _lengths.entries) e.key: e.value},
                onChanged: (v) => setState(() => newLength = v),
              ),
              FilterChip(
                label: const Text('32nds'),
                selected: res == 0.5,
                onSelected: notes.any((n) => n.start % 1 != 0 || n.dur % 1 != 0)
                    ? null
                    : (v) => setState(() => res = v ? 0.5 : 1),
                tooltip: 'Squares half a 16th wide',
              ),
              Row(mainAxisSize: MainAxisSize.min, children: [
                IconButton(
                    tooltip: 'Narrower',
                    onPressed: cellW > 12 ? () => setState(() => cellW -= 4) : null,
                    icon: const Icon(Icons.zoom_out)),
                IconButton(
                    tooltip: 'Wider',
                    onPressed: cellW < 56 ? () => setState(() => cellW += 4) : null,
                    icon: const Icon(Icons.zoom_in)),
              ]),
              TextButton.icon(
                onPressed: notes.isEmpty
                    ? null
                    : () {
                        _remember();
                        notes.clear();
                        _edited();
                      },
                icon: const Icon(Icons.delete_sweep_outlined),
                label: const Text('Clear'),
              ),
            ]),
          ),
          Row(children: [
            SizedBox(width: labelW),
            Expanded(
              child: SingleChildScrollView(
                controller: _bars,
                scrollDirection: Axis.horizontal,
                physics: const NeverScrollableScrollPhysics(),
                child: CustomPaint(
                  size: Size(cols * cellW, header),
                  painter: _BarsPainter(
                      res: res, pickup: pickup, total: total, cellW: cellW, scheme: cs, style: barStyle),
                ),
              ),
            ),
          ]),
          Expanded(
            child: Scrollbar(
              controller: _vertical,
              child: SingleChildScrollView(
                controller: _vertical,
                child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  SizedBox(
                    width: labelW,
                    child: Column(children: [
                      for (final v in rows)
                        Container(
                          height: cellH,
                          alignment: Alignment.centerRight,
                          padding: const EdgeInsets.only(right: 8),
                          color: _isRoot(v) ? cs.primary.withValues(alpha: 0.10) : null,
                          child: Text(_rowLabel(v),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                  fontSize: 11.5,
                                  fontWeight: _isRoot(v) ? FontWeight.w700 : FontWeight.w500,
                                  color: cs.onSurfaceVariant)),
                        ),
                    ]),
                  ),
                  Expanded(
                    child: Scrollbar(
                      controller: _horizontal,
                      child: SingleChildScrollView(
                        controller: _horizontal,
                        scrollDirection: Axis.horizontal,
                        child: Listener(
                          onPointerDown: _mouseDown,
                          onPointerMove: _mouseMove,
                          onPointerUp: _mouseUp,
                          child: GestureDetector(
                            onTapUp: (d) {
                              if (d.kind != PointerDeviceKind.mouse) _tap(d.localPosition);
                            },
                            child: CustomPaint(
                              size: Size(cols * cellW, rows.length * cellH),
                              painter: _BlocksPainter(
                                notes: notes,
                                rows: rows,
                                roots: {for (final v in rows) if (_isRoot(v)) v},
                                res: res,
                                pickup: pickup,
                                total: total,
                                cellW: cellW,
                                cellH: cellH,
                                scheme: cs,
                              ),
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                ]),
              ),
            ),
          ),
          Container(
            padding: const EdgeInsets.fromLTRB(14, 8, 14, 12),
            color: cs.surfaceContainerHigh,
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(
                'Tap a square to put a block there, tap a block to take it away${iconButtons(context) ? ' — or drag '
                    'with the mouse to draw a longer one' : ''}.'
                    '${mode == 'semitone' ? ' Blocks that sound together make a chord.' : ''}'
                    '${pickup > 0 ? ' The shaded start is the lead-in, before the part’s first beat.' : ''}',
                style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant),
              ),
              if (!once && text.isNotEmpty) ...[
                const SizedBox(height: 6),
                SelectableText(text,
                    maxLines: 3,
                    style: const TextStyle(
                        fontFamily: 'monospace',
                        fontFamilyFallback: ['Menlo', 'Consolas', 'DejaVu Sans Mono', 'Courier New'],
                        fontSize: 12,
                        height: 1.3)),
              ],
            ]),
          ),
        ]),
      ),
    );
  }

  bool _isRoot(int v) => mode == 'semitone' && v % 12 == 0;
}

class _BarsPainter extends CustomPainter {
  _BarsPainter({
    required this.res,
    required this.pickup,
    required this.total,
    required this.cellW,
    required this.scheme,
    required this.style,
  });

  final double res, pickup, total, cellW;
  final ColorScheme scheme;
  final TextStyle style;

  @override
  void paint(Canvas canvas, Size size) {
    final text = TextPainter(textDirection: TextDirection.ltr);
    if (pickup > 0) {
      canvas.drawRect(Rect.fromLTWH(0, 0, pickup / res * cellW, size.height),
          Paint()..color = scheme.onSurface.withValues(alpha: 0.08));
    }
    for (var bar = 0; pickup + bar * 16 < total - 1e-9; bar++) {
      final x = (pickup + bar * 16) / res * cellW;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height),
          Paint()
            ..color = scheme.outline.withValues(alpha: 0.9)
            ..strokeWidth = 2);
      text.text = TextSpan(text: '${bar + 1}', style: style);
      text.layout();
      text.paint(canvas, Offset(x + 5, (size.height - text.height) / 2));
    }
  }

  @override
  bool shouldRepaint(covariant _BarsPainter old) =>
      old.res != res || old.total != total || old.cellW != cellW || old.pickup != pickup || old.scheme != scheme;
}

class _BlocksPainter extends CustomPainter {
  _BlocksPainter({
    required this.notes,
    required this.rows,
    required this.roots,
    required this.res,
    required this.pickup,
    required this.total,
    required this.cellW,
    required this.cellH,
    required this.scheme,
  });

  final List<BlockNote> notes;
  final List<int> rows;
  final Set<int> roots;
  final double res, pickup, total, cellW, cellH;
  final ColorScheme scheme;

  @override
  void paint(Canvas canvas, Size size) {
    final cs = scheme;
    final w = size.width, h = size.height;
    // Rows: every other one a shade darker, the key's root lit.
    for (var i = 0; i < rows.length; i++) {
      final c = roots.contains(rows[i])
          ? cs.primary.withValues(alpha: 0.10)
          : (i.isOdd ? cs.surfaceContainerHighest : cs.surfaceContainerLow);
      canvas.drawRect(Rect.fromLTWH(0, i * cellH, w, cellH), Paint()..color = c);
    }
    // The lead-in, before the first beat.
    if (pickup > 0) {
      canvas.drawRect(
          Rect.fromLTWH(0, 0, pickup / res * cellW, h), Paint()..color = cs.onSurface.withValues(alpha: 0.08));
    }
    // Columns: 16ths faint, beats stronger, bars strongest.
    final cols = (total / res).ceil();
    for (var c = 0; c <= cols; c++) {
      final fromBar = c * res - pickup;
      final bar = fromBar >= -1e-9 && (fromBar % 16).abs() < 1e-9;
      final beat = fromBar >= -1e-9 && (fromBar % 4).abs() < 1e-9;
      final x = c * cellW;
      canvas.drawLine(
          Offset(x, 0),
          Offset(x, h),
          Paint()
            ..color = cs.outline.withValues(alpha: bar ? 0.9 : beat ? 0.45 : 0.16)
            ..strokeWidth = bar ? 2 : 1);
    }
    // The blocks, a colour per line.
    final colors = [cs.primary, cs.tertiary, cs.secondary, Colors.orange.shade600, Colors.teal.shade400];
    for (final n in notes) {
      final r = rows.indexOf(n.value);
      if (r < 0) continue;
      final rect = Rect.fromLTWH(
          n.start / res * cellW + 1.5, r * cellH + 2.5, max(3.0, n.dur / res * cellW - 3), cellH - 5);
      final box = RRect.fromRectAndRadius(rect, const Radius.circular(4));
      canvas.drawRRect(box, Paint()..color = colors[n.voice % colors.length]);
      canvas.drawRRect(
          box,
          Paint()
            ..color = Colors.black.withValues(alpha: 0.25)
            ..style = PaintingStyle.stroke);
    }
  }

  @override
  bool shouldRepaint(covariant _BlocksPainter old) => true;
}
