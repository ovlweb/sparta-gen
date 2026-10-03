// Cutting a sample by eye: the source's sound as a waveform and its frames as a film strip, the cut between
// two handles — starting from where the sample is cut now. Typing the times stays as an option.

import 'dart:async';
import 'dart:math';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../state/app_state.dart';
import 'common.dart';

/// Opens the cutter; the cut chosen (start, end in seconds of the source), or null.
Future<(double, double)?> showSampleCutter(
  BuildContext context, {
  required AppState app,
  required String title,
  required double start,
  required double end,
  required double sourceDuration,
  String? sourcePath,
  String source = 'main',
}) =>
    showDialog<(double, double)>(
      context: context,
      builder: (context) => SampleCutter(
        app: app,
        title: title,
        start: start,
        end: end,
        sourceDuration: sourceDuration,
        sourcePath: sourcePath,
        source: source,
      ),
    );

class SampleCutter extends StatefulWidget {
  const SampleCutter({
    super.key,
    required this.app,
    required this.title,
    required this.start,
    required this.end,
    required this.sourceDuration,
    this.sourcePath,
    this.source = 'main',
  });

  final AppState app;
  final String title;
  final double start;
  final double end;
  final double sourceDuration;
  final String? sourcePath;

  /// Which of the project's videos it is cut from ("main", or another's id).
  final String source;

  @override
  State<SampleCutter> createState() => _SampleCutterState();
}

enum _Grab { start, end, both, view }

/// Peaks of the source's sound between two times (0-1, one scale for the whole video).
class _Peaks {
  const _Peaks(this.start, this.end, this.values);

  final double start;
  final double end;
  final List<double> values;

  double get perSecond => values.length / max(end - start, 1e-6);
}

class _SampleCutterState extends State<SampleCutter> {
  static const _minCut = 0.03;
  static const _minSpan = 0.25;
  late double _a = widget.start; // the cut
  late double _z = widget.end;
  double _v0 = 0; // the stretch of the source shown
  double _v1 = 1;
  late double _shownA = _a; // the frames shown at the cut's ends (updated when a handle is let go)
  late double _shownZ = _z;
  _Peaks? _overview; // the whole video, loaded once: drawn at once wherever the view goes
  _Peaks? _detail; // the stretch in view, sharper, loaded when the view stops moving
  int _request = 0;
  Timer? _debounce;
  _Grab? _grab;
  // Where a pinch started: the view then, and the time under the fingers.
  double _gestureSpan = 1;
  double _gestureFocus = 0;
  bool _typing = false;
  final _startC = TextEditingController();
  final _endC = TextEditingController();

  double get _total => max(widget.sourceDuration, _z + 0.1);
  double get _span => _v1 - _v0;

  @override
  void initState() {
    super.initState();
    _fit();
    _fillFields();
    _loadOverview();
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _startC.dispose();
    _endC.dispose();
    super.dispose();
  }

  void _fillFields() {
    _startC.text = _a.toStringAsFixed(3);
    _endC.text = _z.toStringAsFixed(3);
  }

  /// The view around the cut: three times its length, at least a second and a half.
  void _fit() {
    final span = min(_total, max(1.5, (_z - _a) * 3));
    _setView((_a + _z) / 2 - span / 2, span);
  }

  /// Shows [span] seconds from [v0] (kept inside the video) — the waveform follows at once, from what is loaded.
  void _setView(double v0, double span) {
    span = span.clamp(min(_minSpan, _total), _total).toDouble();
    v0 = v0.clamp(0.0, max(0.0, _total - span)).toDouble();
    _v0 = v0;
    _v1 = v0 + span;
    _loadDetail();
  }

  Future<void> _loadOverview() async {
    final total = _total;
    final peaks = await widget.app.waveform(0, total, n: 4000, source: widget.source);
    if (!mounted || peaks == null || peaks.isEmpty) return;
    setState(() => _overview = _Peaks(0, total, peaks));
    _loadDetail();
  }

  /// Once the view has stopped moving: its stretch (and as much again around it) in detail, if the whole video's
  /// peaks are too coarse for it.
  void _loadDetail() {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 200), () async {
      final overview = _overview;
      final have = _detail;
      if (overview != null && overview.perSecond * _span >= 500) return;
      if (have != null && have.start <= _v0 && have.end >= _v1 && have.perSecond * _span >= 500) return;
      final ask = ++_request;
      final a = max(0.0, _v0 - _span / 2);
      final z = min(_total, _v1 + _span / 2);
      final peaks = await widget.app.waveform(a, z, n: 1600, source: widget.source);
      if (!mounted || ask != _request || peaks == null || peaks.isEmpty) return;
      setState(() => _detail = _Peaks(a, z, peaks));
    });
  }

  /// Zooms by [factor] (above 1: out) keeping the time at [at] (default: the middle of the view) where it is.
  void _zoom(double factor, {double? at, double? atFraction}) => setState(() {
        final t = at ?? (_v0 + _v1) / 2;
        final f = atFraction ?? 0.5;
        final span = _span * factor;
        _setView(t - f * span.clamp(min(_minSpan, _total), _total), span);
      });

  double _timeAt(double x, double width) => _v0 + (x / width).clamp(0.0, 1.0) * _span;

  void _gestureStart(ScaleStartDetails d, double width) {
    _gestureSpan = _span;
    _gestureFocus = _timeAt(d.localFocalPoint.dx, width);
    // Two fingers, or a trackpad's two-finger scroll or pinch, move the view; one finger or the mouse picks up
    // what is under it.
    if (d.pointerCount > 1 || d.kind == PointerDeviceKind.trackpad) {
      _grab = _Grab.view;
      return;
    }
    final t = _gestureFocus;
    final near = 14 * _span / width;
    if ((t - _a).abs() <= near && (t - _a).abs() <= (t - _z).abs()) {
      _grab = _Grab.start;
    } else if ((t - _z).abs() <= near) {
      _grab = _Grab.end;
    } else if (t > _a && t < _z) {
      _grab = _Grab.both;
    } else {
      _grab = _Grab.view;
    }
  }

  void _gestureUpdate(ScaleUpdateDetails d, double width) {
    setState(() {
      if (d.scale != 1.0) {
        // A pinch: the view grows or shrinks around the fingers.
        final span = (_gestureSpan / d.scale).clamp(min(_minSpan, _total), _total).toDouble();
        _setView(_gestureFocus - (d.localFocalPoint.dx / width) * span, span);
        return;
      }
      final dt = d.focalPointDelta.dx / width * _span;
      switch (_grab) {
        case _Grab.start:
          _a = (_a + dt).clamp(0.0, _z - _minCut).toDouble();
        case _Grab.end:
          _z = (_z + dt).clamp(_a + _minCut, _total).toDouble();
        case _Grab.both:
          final len = _z - _a;
          final a = (_a + dt).clamp(0.0, _total - len).toDouble();
          _a = a;
          _z = a + len;
        case _Grab.view:
          _setView(_v0 - dt, _span);
        case null:
          break;
      }
    });
  }

  void _gestureEnd() {
    _grab = null;
    setState(() {
      _shownA = _a;
      _shownZ = _z;
      _fillFields();
    });
  }

  /// The mouse wheel zooms around the pointer; a sideways scroll (or Shift + wheel) moves the view. The dialog
  /// under it does not scroll meanwhile.
  void _wheel(PointerSignalEvent e, double width) {
    if (e is! PointerScrollEvent) return;
    GestureBinding.instance.pointerSignalResolver.register(e, (event) {
      final s = event as PointerScrollEvent;
      final dx = s.scrollDelta.dx != 0 ? s.scrollDelta.dx : (HardwareKeyboard.instance.isShiftPressed ? s.scrollDelta.dy : 0.0);
      if (dx != 0) {
        setState(() => _setView(_v0 + dx / width * _span, _span));
      } else if (s.scrollDelta.dy != 0) {
        final f = (s.localPosition.dx / width).clamp(0.0, 1.0).toDouble();
        _zoom(exp(s.scrollDelta.dy * 0.004), at: _v0 + f * _span, atFraction: f);
      }
    });
  }

  void _useTyped() {
    final a = double.tryParse(_startC.text.replaceAll(',', '.'));
    final z = double.tryParse(_endC.text.replaceAll(',', '.'));
    if (a == null || z == null || z - a < _minCut || a < 0) {
      widget.app.fail('The end must be after the start (in seconds of the video).');
      return;
    }
    setState(() {
      _a = a;
      _z = z;
      _shownA = a;
      _shownZ = z;
      _fit();
    });
  }

  void _play(double a, double z, String tag) {
    final src = widget.sourcePath;
    if (src == null) return;
    Players.playSound(src, tag: tag, start: a, end: z, label: tag == 'cutter' ? 'the cut' : 'around the cut');
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final t = Theme.of(context).textTheme;
    final app = widget.app;
    final len = _z - _a;
    return Dialog(
      insetPadding: const EdgeInsets.all(16),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 940),
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 18, 20, 16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
            Row(children: [
              Expanded(child: Text('Cut ${widget.title}', style: t.titleLarge)),
              IconButton(tooltip: 'Close', icon: const Icon(Icons.close), onPressed: () => Navigator.pop(context)),
            ]),
            Text('Drag the handles to where the sample starts and ends; drag inside the cut to move it, outside it to '
                'look around. It starts where it is cut now.',
                style: t.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
            const SizedBox(height: 12),
            // What the clip looks like where it starts and where it ends.
            Row(children: [
              Expanded(child: _frame(app.thumbUrl(_shownA + 0.02, width: 480, height: 270, source: widget.source), 'starts on ${fmtTime(_shownA)}')),
              const SizedBox(width: 10),
              Expanded(child: _frame(app.thumbUrl(max(_shownA, _shownZ - 0.04), width: 480, height: 270, source: widget.source),
                  'ends on ${fmtTime(_shownZ)}')),
            ]),
            const SizedBox(height: 12),
            // Film strip over the waveform, the cut over both.
            LayoutBuilder(builder: (context, box) {
              final w = box.maxWidth;
              return Listener(
                onPointerSignal: (e) => _wheel(e, w),
                child: GestureDetector(
                  onScaleStart: (d) => _gestureStart(d, w),
                  onScaleUpdate: (d) => _gestureUpdate(d, w),
                  onScaleEnd: (_) => _gestureEnd(),
                  child: MouseRegion(
                    cursor: SystemMouseCursors.resizeColumn,
                    child: SizedBox(
                      key: const ValueKey('cutter-view'),
                      height: 64 + 110,
                      child: ClipRect(
                        child: Stack(children: [
                          Positioned(left: 0, right: 0, top: 0, height: 60, child: _filmStrip(w)),
                          Positioned(
                            left: 0,
                            right: 0,
                            top: 64,
                            height: 110,
                            child: CustomPaint(
                              painter: _WavePainter(
                                v0: _v0,
                                v1: _v1,
                                overview: _overview,
                                detail: _detail,
                                color: cs.onSurfaceVariant,
                                background: cs.surfaceContainerHighest,
                              ),
                            ),
                          ),
                          // The cut: shaded, with a handle at each end.
                          Positioned.fill(
                            child: IgnorePointer(
                              child: CustomPaint(
                                painter: _CutPainter(
                                  a: (_a - _v0) / _span,
                                  z: (_z - _v0) / _span,
                                  color: cs.primary,
                                ),
                              ),
                            ),
                          ),
                        ]),
                      ),
                    ),
                  ),
                ),
              );
            }),
            const SizedBox(height: 4),
            Row(children: [
              Text(fmtTime(_v0), key: const ValueKey('cutter-from'), style: t.bodySmall),
              const Spacer(),
              Text('${fmtTime(_a)} – ${fmtTime(_z)}  ·  ${len.toStringAsFixed(2)} s',
                  style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
              const Spacer(),
              Text(fmtTime(_v1), key: const ValueKey('cutter-to'), style: t.bodySmall),
            ]),
            const SizedBox(height: 10),
            Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
              PlayToggle(
                tag: 'cutter',
                play: widget.sourcePath == null ? null : () => _play(_a, _z, 'cutter'),
                label: 'Play the cut',
              ),
              PlayToggle(
                tag: 'cutter:view',
                outlined: true,
                icon: Icons.hearing,
                play: widget.sourcePath == null ? null : () => _play(_v0, _v1, 'cutter:view'),
                label: 'Play around it',
              ),
              IconButton(tooltip: 'Zoom in', icon: const Icon(Icons.zoom_in), onPressed: () => _zoom(1 / 1.6)),
              IconButton(tooltip: 'Zoom out', icon: const Icon(Icons.zoom_out), onPressed: () => _zoom(1.6)),
              AdaptiveButton.text(
                onPressed: () => setState(_fit),
                icon: const Icon(Icons.center_focus_strong),
                label: const Text('Around the cut'),
              ),
              AdaptiveButton.text(
                onPressed: () => setState(() => _typing = !_typing),
                icon: Icon(_typing ? Icons.expand_less : Icons.keyboard),
                label: const Text('Type the times'),
              ),
            ]),
            if (_typing)
              Padding(
                padding: const EdgeInsets.only(top: 10),
                child: Row(children: [
                  Expanded(child: _field(_startC, 'from (s)')),
                  const SizedBox(width: 8),
                  Expanded(child: _field(_endC, 'to (s)')),
                  const SizedBox(width: 8),
                  OutlinedButton(onPressed: _useTyped, child: const Text('Set')),
                ]),
              ),
            const SizedBox(height: 16),
            Row(mainAxisAlignment: MainAxisAlignment.end, children: [
              TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancel')),
              const SizedBox(width: 8),
              AdaptiveButton.filled(
                onPressed: () => Navigator.pop(context, (_a, _z)),
                icon: const Icon(Icons.content_cut),
                label: const Text('Use this cut'),
              ),
            ]),
          ]),
        ),
      ),
    );
  }

  /// Frames of the video along the view, at times on a fixed grid (a round step for the zoom): moving the view
  /// slides them along and asks only for the ones coming in; zooming asks again only when the step changes.
  Widget _filmStrip(double width) {
    const steps = [0.05, 0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 5.0, 10.0, 15.0, 30.0, 60.0, 120.0, 300.0];
    final step = steps.firstWhere((s) => s >= _span / 8, orElse: () => steps.last);
    final first = (_v0 / step).floor();
    final last = (_v1 / step).ceil();
    final tile = step / _span * width;
    return Stack(children: [
      for (var k = first; k < last; k++)
        Positioned(
          left: (k * step - _v0) / _span * width,
          top: 0,
          bottom: 0,
          width: max(1.0, tile - 2),
          child: Image.network(
            widget.app.thumbUrl(min(_total, (k + 0.5) * step), source: widget.source),
            fit: BoxFit.cover,
            gaplessPlayback: true,
            errorBuilder: (_, _, _) => Container(color: Colors.black),
          ),
        ),
    ]);
  }

  Widget _frame(String url, String caption) => Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(8),
          child: AspectRatio(
            aspectRatio: 16 / 9,
            child: Container(
              color: Colors.black,
              child: Image.network(url, fit: BoxFit.cover, gaplessPlayback: true,
                  errorBuilder: (_, _, _) => const Icon(Icons.graphic_eq, color: Colors.white38)),
            ),
          ),
        ),
        const SizedBox(height: 4),
        Text(caption, style: Theme.of(context).textTheme.bodySmall),
      ]);

  Widget _field(TextEditingController c, String label) => TextField(
        controller: c,
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        decoration: InputDecoration(labelText: label),
        onSubmitted: (_) => _useTyped(),
      );
}

/// The sound between v0 and v1: a peak per column of two pixels, mirrored around the middle — from the detailed peaks
/// where they cover it, else from the whole video's.
class _WavePainter extends CustomPainter {
  _WavePainter({
    required this.v0,
    required this.v1,
    required this.overview,
    required this.detail,
    required this.color,
    required this.background,
  });

  final double v0;
  final double v1;
  final _Peaks? overview;
  final _Peaks? detail;
  final Color color;
  final Color background;

  static double _peak(_Peaks p, double t0, double t1) {
    final n = p.values.length;
    final span = p.end - p.start;
    if (span <= 0 || n == 0) return 0;
    var i0 = ((t0 - p.start) / span * n).floor();
    var i1 = ((t1 - p.start) / span * n).ceil();
    i0 = i0.clamp(0, n - 1);
    i1 = i1.clamp(i0 + 1, n);
    var m = 0.0;
    for (var i = i0; i < i1; i++) {
      if (p.values[i] > m) m = p.values[i];
    }
    return m;
  }

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRRect(RRect.fromRectAndRadius(Offset.zero & size, const Radius.circular(6)), Paint()..color = background);
    final span = v1 - v0;
    if (span <= 0 || (overview == null && detail == null)) return;
    final mid = size.height / 2;
    const col = 2.0;
    final paint = Paint()
      ..color = color
      ..strokeWidth = col - 0.5;
    final d = detail;
    final useDetail = d != null && (overview == null || d.perSecond > overview!.perSecond);
    for (var x = 0.0; x < size.width; x += col) {
      final t0 = v0 + x / size.width * span;
      final t1 = v0 + (x + col) / size.width * span;
      _Peaks? src;
      if (useDetail && t0 >= d.start && t1 <= d.end) {
        src = d;
      } else if (overview != null) {
        src = overview;
      } else if (d != null && t1 > d.start && t0 < d.end) {
        src = d;
      }
      if (src == null || t1 <= src.start || t0 >= src.end) continue;
      final h = max(0.5, _peak(src, t0, t1) * (mid - 4));
      canvas.drawLine(Offset(x + col / 2, mid - h), Offset(x + col / 2, mid + h), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _WavePainter old) =>
      old.v0 != v0 || old.v1 != v1 || old.overview != overview || old.detail != detail || old.color != color;
}

/// The cut over the strip and the waveform: shaded between its ends, a handle at each.
class _CutPainter extends CustomPainter {
  _CutPainter({required this.a, required this.z, required this.color});

  final double a; // 0-1 across the view (may be outside it)
  final double z;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    final xa = a * size.width;
    final xz = z * size.width;
    final shade = Paint()..color = Colors.black.withValues(alpha: 0.45);
    if (xa > 0) canvas.drawRect(Rect.fromLTRB(0, 0, min(xa, size.width), size.height), shade);
    if (xz < size.width) canvas.drawRect(Rect.fromLTRB(max(0, xz), 0, size.width, size.height), shade);
    canvas.drawRect(Rect.fromLTRB(xa, 0, xz, size.height), Paint()..color = color.withValues(alpha: 0.12));
    final line = Paint()
      ..color = color
      ..strokeWidth = 3;
    for (final x in [xa, xz]) {
      if (x < -2 || x > size.width + 2) continue;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), line);
      canvas.drawRRect(
          RRect.fromRectAndRadius(Rect.fromCenter(center: Offset(x, size.height / 2), width: 12, height: 34),
              const Radius.circular(4)),
          Paint()..color = color);
    }
  }

  @override
  bool shouldRepaint(covariant _CutPainter old) => old.a != a || old.z != z || old.color != color;
}
