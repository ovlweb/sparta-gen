// Cutting a sample by eye: the source's sound as a waveform and its frames as a film strip, the cut between
// two handles — starting from where the sample is cut now. Typing the times stays as an option.

import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';

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
  });

  final AppState app;
  final String title;
  final double start;
  final double end;
  final double sourceDuration;
  final String? sourcePath;

  @override
  State<SampleCutter> createState() => _SampleCutterState();
}

enum _Grab { start, end, both, view }

class _SampleCutterState extends State<SampleCutter> {
  static const _minCut = 0.03;
  late double _a = widget.start; // the cut
  late double _z = widget.end;
  late double _v0; // the stretch of the source shown
  late double _v1;
  late double _shownA = _a; // the frames shown at the cut's ends (updated when a handle is let go)
  late double _shownZ = _z;
  List<double>? _peaks;
  int _request = 0;
  Timer? _debounce;
  _Grab? _grab;
  bool _typing = false;
  final _startC = TextEditingController();
  final _endC = TextEditingController();

  double get _total => max(widget.sourceDuration, _z + 0.1);

  @override
  void initState() {
    super.initState();
    _fit();
    _fillFields();
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

  void _setView(double v0, double span) {
    span = span.clamp(min(0.25, _total), _total).toDouble();
    v0 = v0.clamp(0.0, max(0.0, _total - span)).toDouble();
    _v0 = v0;
    _v1 = v0 + span;
    _load();
  }

  void _load() {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 120), () async {
      final ask = ++_request;
      final (a, z) = (_v0, _v1);
      final peaks = await widget.app.waveform(a, z, n: 700);
      if (!mounted || ask != _request) return;
      setState(() => _peaks = peaks);
    });
  }

  void _zoom(double factor) => setState(() {
        final mid = (_a + _z) / 2;
        final span = (_v1 - _v0) * factor;
        _setView(mid - span / 2, span);
      });

  double _timeAt(double x, double width) => _v0 + (x / width).clamp(0.0, 1.0) * (_v1 - _v0);

  void _panStart(Offset p, double width) {
    final t = _timeAt(p.dx, width);
    final perPx = (_v1 - _v0) / width;
    final near = 14 * perPx;
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

  void _panUpdate(DragUpdateDetails d, double width) {
    final dt = d.delta.dx / width * (_v1 - _v0);
    setState(() {
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
          final span = _v1 - _v0;
          _v0 = (_v0 - dt).clamp(0.0, max(0.0, _total - span)).toDouble();
          _v1 = _v0 + span;
        case null:
          break;
      }
    });
  }

  void _panEnd() {
    if (_grab == _Grab.view) _load();
    _grab = null;
    setState(() {
      _shownA = _a;
      _shownZ = _z;
      _fillFields();
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
    Players.playSound(src, tag: tag, start: a, end: z);
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
              Expanded(child: _frame(app.thumbUrl(_shownA + 0.02, width: 480, height: 270), 'starts on ${fmtTime(_shownA)}')),
              const SizedBox(width: 10),
              Expanded(child: _frame(app.thumbUrl(max(_shownA, _shownZ - 0.04), width: 480, height: 270), 'ends on ${fmtTime(_shownZ)}')),
            ]),
            const SizedBox(height: 12),
            // Film strip over the waveform, the cut over both.
            LayoutBuilder(builder: (context, box) {
              final w = box.maxWidth;
              const strip = 8;
              return GestureDetector(
                onPanStart: (d) => _panStart(d.localPosition, w),
                onPanUpdate: (d) => _panUpdate(d, w),
                onPanEnd: (_) => _panEnd(),
                child: MouseRegion(
                  cursor: SystemMouseCursors.resizeColumn,
                  child: SizedBox(
                    height: 64 + 110,
                    child: Stack(children: [
                      Positioned(
                        left: 0,
                        right: 0,
                        top: 0,
                        height: 60,
                        child: Row(children: [
                          for (var i = 0; i < strip; i++)
                            Expanded(
                              child: Padding(
                                padding: const EdgeInsets.only(right: 2),
                                child: Image.network(
                                  app.thumbUrl(_v0 + (i + 0.5) * (_v1 - _v0) / strip),
                                  fit: BoxFit.cover,
                                  gaplessPlayback: true,
                                  errorBuilder: (_, _, _) => Container(color: Colors.black),
                                ),
                              ),
                            ),
                        ]),
                      ),
                      Positioned(
                        left: 0,
                        right: 0,
                        top: 64,
                        height: 110,
                        child: CustomPaint(
                          painter: _WavePainter(
                            peaks: _peaks,
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
                              a: (_a - _v0) / (_v1 - _v0),
                              z: (_z - _v0) / (_v1 - _v0),
                              color: cs.primary,
                            ),
                          ),
                        ),
                      ),
                    ]),
                  ),
                ),
              );
            }),
            const SizedBox(height: 4),
            Row(children: [
              Text(fmtTime(_v0), style: t.bodySmall),
              const Spacer(),
              Text('${fmtTime(_a)} – ${fmtTime(_z)}  ·  ${len.toStringAsFixed(2)} s',
                  style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
              const Spacer(),
              Text(fmtTime(_v1), style: t.bodySmall),
            ]),
            const SizedBox(height: 10),
            Wrap(spacing: 8, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
              FilledButton.tonalIcon(
                onPressed: widget.sourcePath == null ? null : () => _play(_a, _z, 'cutter'),
                icon: const Icon(Icons.play_arrow),
                label: const Text('Play the cut'),
              ),
              OutlinedButton.icon(
                onPressed: widget.sourcePath == null ? null : () => _play(_v0, _v1, 'cutter:view'),
                icon: const Icon(Icons.hearing),
                label: const Text('Play around it'),
              ),
              IconButton(tooltip: 'Zoom in', icon: const Icon(Icons.zoom_in), onPressed: () => _zoom(1 / 1.6)),
              IconButton(tooltip: 'Zoom out', icon: const Icon(Icons.zoom_out), onPressed: () => _zoom(1.6)),
              TextButton.icon(
                onPressed: () => setState(_fit),
                icon: const Icon(Icons.center_focus_strong),
                label: const Text('Around the cut'),
              ),
              TextButton.icon(
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
              FilledButton.icon(
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

/// The sound: a peak per pixel column, mirrored around the middle.
class _WavePainter extends CustomPainter {
  _WavePainter({required this.peaks, required this.color, required this.background});

  final List<double>? peaks;
  final Color color;
  final Color background;

  @override
  void paint(Canvas canvas, Size size) {
    canvas.drawRRect(RRect.fromRectAndRadius(Offset.zero & size, const Radius.circular(6)), Paint()..color = background);
    final p = peaks;
    if (p == null || p.isEmpty) return;
    final mid = size.height / 2;
    final paint = Paint()
      ..color = color
      ..strokeWidth = max(1.0, size.width / p.length);
    for (var i = 0; i < p.length; i++) {
      final x = (i + 0.5) * size.width / p.length;
      final h = max(0.5, p[i] * (mid - 4));
      canvas.drawLine(Offset(x, mid - h), Offset(x, mid + h), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _WavePainter old) => old.peaks != peaks || old.color != color;
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
