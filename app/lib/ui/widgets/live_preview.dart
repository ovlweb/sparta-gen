// The remix's picture at any moment, drawn by the engine with the current look: every change shows at once,
// no render needed. Scrub the timeline, jump to a part, step a beat at a time.

import 'dart:math';

import 'package:flutter/material.dart';

import '../../state/app_state.dart';
import 'common.dart';

class LivePreview extends StatefulWidget {
  const LivePreview({super.key, required this.app, this.title = 'Live preview'});

  final AppState app;
  final String title;

  @override
  State<LivePreview> createState() => _LivePreviewState();
}

class _LivePreviewState extends State<LivePreview> {
  double? _t; // the moment shown (seconds into the remix)
  double? _drag; // while the slider is dragged

  AppState get app => widget.app;

  Map<String, dynamic> get _arr => app.arrangementSummary ?? const {};

  /// The parts, each with its start in seconds (counted from the bars when the engine did not say).
  List<Map<String, dynamic>> get _sections {
    var t = 0.0;
    return [
      for (final s in (_arr['sections'] as List? ?? const []))
        () {
          final m = (s as Map).cast<String, dynamic>();
          final start = (m['start'] as num?)?.toDouble() ?? t;
          t = start + ((m['bars'] as num?) ?? 0).toDouble() * 4 * _beat;
          return {...m, 'start': start};
        }(),
    ];
  }

  double get _duration => ((_arr['duration'] as num?) ?? 0).toDouble();

  double get _beat => 60 / (((_arr['bpm'] as num?) ?? 140).toDouble());

  double _start(Map<String, dynamic> s) => ((s['start'] as num?) ?? 0).toDouble();

  /// A moment of a part that shows its look: past its opening hit.
  double _into(Map<String, dynamic> s) => _start(s) + 2.5 * _beat;

  double get _default {
    for (final s in _sections) {
      if ('${s['kind']}'.startsWith('chorus')) return _into(s);
    }
    return min(2.0, _duration / 2);
  }

  double _clamp(double t) => t.clamp(0.0, max(0.0, _duration - 0.05)).toDouble();

  int _sectionAt(double t) {
    final secs = _sections;
    for (var i = secs.length - 1; i >= 0; i--) {
      if (_start(secs[i]) <= t + 1e-6) return i;
    }
    return 0;
  }

  void _go(double t) => setState(() {
        _drag = null;
        _t = _clamp(t);
      });

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    if (!app.hasSource || !app.analyzed || _duration <= 0) {
      return SectionCard(
        title: widget.title,
        child: EmptyState(
          icon: Icons.image_outlined,
          title: app.hasSource ? 'Cut the samples to see your remix here' : 'Open a video to see your remix here',
          message: 'Then every change you make shows here at once, at any moment of the remix.',
          action: FilledButton.tonal(
            onPressed: () => app.go(app.hasSource ? AppPage.samples : AppPage.source),
            child: Text(app.hasSource ? 'Go to Samples' : 'Go to Source'),
          ),
        ),
      );
    }
    final shown = _clamp(_t ?? _default);
    final pos = _clamp(_drag ?? shown);
    final secs = _sections;
    final si = _sectionAt(pos);
    final sec = secs.isEmpty ? null : secs[si];
    return SectionCard(
      title: widget.title,
      subtitle: 'The picture at ${fmtTime(pos)}${sec == null ? '' : ' — ${_name(sec)}'}, with every change as you make it.',
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: AspectRatio(
            aspectRatio: 16 / 9,
            child: Container(
              color: Colors.black,
              child: Image.network(
                app.frameUrl(shown),
                key: const ValueKey('live-preview'),
                gaplessPlayback: true, // the last picture stays while the next is drawn
                fit: BoxFit.contain,
                loadingBuilder: (context, child, progress) => Stack(fit: StackFit.expand, children: [
                  child,
                  if (progress != null)
                    const Align(
                      alignment: Alignment.topRight,
                      child: Padding(
                        padding: EdgeInsets.all(10),
                        child: SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
                      ),
                    ),
                ]),
                errorBuilder: (context, error, _) => Center(
                  child: Text('The picture could not be drawn.', style: TextStyle(color: cs.onSurfaceVariant)),
                ),
              ),
            ),
          ),
        ),
        const SizedBox(height: 10),
        _PartsStrip(
          sections: secs,
          duration: _duration,
          position: pos,
          current: si,
          onTap: (i) => _go(_into(secs[i])),
        ),
        Slider(
          value: pos,
          min: 0,
          max: max(_duration - 0.05, 0.01),
          onChanged: (v) => setState(() => _drag = v),
          onChangeEnd: _go,
        ),
        Wrap(alignment: WrapAlignment.center, spacing: 4, children: [
          IconButton(
            tooltip: 'The part before',
            icon: const Icon(Icons.skip_previous),
            onPressed: si > 0 ? () => _go(_into(secs[si - 1])) : null,
          ),
          IconButton(
            tooltip: 'A beat back',
            icon: const Icon(Icons.chevron_left),
            onPressed: () => _go(pos - _beat),
          ),
          IconButton(
            tooltip: 'A 16th back',
            icon: const Icon(Icons.keyboard_arrow_left),
            onPressed: () => _go(pos - _beat / 4),
          ),
          IconButton(
            tooltip: 'A 16th on',
            icon: const Icon(Icons.keyboard_arrow_right),
            onPressed: () => _go(pos + _beat / 4),
          ),
          IconButton(
            tooltip: 'A beat on',
            icon: const Icon(Icons.chevron_right),
            onPressed: () => _go(pos + _beat),
          ),
          IconButton(
            tooltip: 'The next part',
            icon: const Icon(Icons.skip_next),
            onPressed: si < secs.length - 1 ? () => _go(_into(secs[si + 1])) : null,
          ),
        ]),
      ]),
    );
  }

  static String _name(Map<String, dynamic> s) {
    final n = '${s['name'] ?? ''}'.trim();
    return n.isNotEmpty ? n : (partNames['${s['kind']}'] ?? '${s['kind']}');
  }
}

/// The remix's parts side by side (as long as they last), the one shown marked; tap one to see it.
class _PartsStrip extends StatelessWidget {
  const _PartsStrip({
    required this.sections,
    required this.duration,
    required this.position,
    required this.current,
    required this.onTap,
  });

  final List<Map<String, dynamic>> sections;
  final double duration;
  final double position;
  final int current;
  final ValueChanged<int> onTap;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return SizedBox(
      height: 30,
      child: LayoutBuilder(builder: (context, box) {
        final starts = [for (final s in sections) ((s['start'] as num?) ?? 0).toDouble()];
        return Stack(children: [
          Row(children: [
            for (var i = 0; i < sections.length; i++)
              Expanded(
                flex: max(1, (((i + 1 < starts.length ? starts[i + 1] : duration) - starts[i]) * 100).round()),
                child: Tooltip(
                  message: _LivePreviewState._name(sections[i]),
                  child: InkWell(
                    onTap: () => onTap(i),
                    child: Container(
                      margin: const EdgeInsets.only(right: 1),
                      decoration: BoxDecoration(
                        color: partColor('${sections[i]['kind']}').withValues(alpha: i == current ? 1 : 0.6),
                        borderRadius: BorderRadius.circular(4),
                      ),
                      alignment: Alignment.center,
                      child: Text(_LivePreviewState._name(sections[i]),
                          maxLines: 1,
                          overflow: TextOverflow.clip,
                          style: TextStyle(
                              fontSize: 10.5,
                              fontWeight: FontWeight.w600,
                              color: onPartColor('${sections[i]['kind']}'))),
                    ),
                  ),
                ),
              ),
          ]),
          if (duration > 0)
            Positioned(
              left: (box.maxWidth * position / duration).clamp(0.0, box.maxWidth - 2),
              top: 0,
              bottom: 0,
              child: IgnorePointer(child: Container(width: 2, color: cs.onSurface)),
            ),
        ]);
      }),
    );
  }
}
