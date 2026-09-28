import 'package:flutter/material.dart';
import 'package:media_kit/media_kit.dart';
import 'package:media_kit_video/media_kit_video.dart';

/// Native players (media_kit) can be switched off — widget tests run without them.
class Players {
  static bool enabled = true;
  static Player? _sample;
  static final ValueNotifier<String?> playing = ValueNotifier(null);

  /// Play a short sound (a sample, or a stretch of the source) — one at a time, never a window.
  static Future<void> playSound(String uri, {String? tag, double? start, double? end}) async {
    if (!enabled) return;
    final pl = _sample ??= Player(configuration: const PlayerConfiguration(vo: 'null', title: 'Sparta Gen'));
    final id = tag ?? uri;
    playing.value = id;
    Duration? d(double? s) => s == null ? null : Duration(microseconds: (s * 1e6).round());
    await pl.open(Media(uri, start: d(start), end: d(end)));
    pl.stream.completed.firstWhere((c) => c).then((_) {
      if (playing.value == id) playing.value = null;
    });
  }

  static Future<void> stopSound() async {
    playing.value = null;
    await _sample?.stop();
  }

  static Future<void> dispose() async {
    await _sample?.dispose();
    _sample = null;
  }
}

class PageBody extends StatelessWidget {
  const PageBody({super.key, required this.title, this.subtitle, required this.children, this.actions = const []});

  final String title;
  final String? subtitle;
  final List<Widget> children;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return ListView(
      padding: const EdgeInsets.fromLTRB(24, 20, 24, 32),
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: t.headlineSmall?.copyWith(fontWeight: FontWeight.w700)),
                if (subtitle != null) ...[
                  const SizedBox(height: 4),
                  Text(subtitle!, style: t.bodyMedium?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant)),
                ],
              ]),
            ),
            ...actions,
          ],
        ),
        const SizedBox(height: 18),
        for (final c in children) ...[c, const SizedBox(height: 16)],
      ],
    );
  }
}

class SectionCard extends StatelessWidget {
  const SectionCard({super.key, this.title, this.subtitle, required this.child, this.trailing, this.padding});

  final String? title;
  final String? subtitle;
  final Widget child;
  final Widget? trailing;
  final EdgeInsets? padding;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: padding ?? const EdgeInsets.all(18),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          if (title != null)
            Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(title!, style: t.titleMedium?.copyWith(fontWeight: FontWeight.w600)),
                  if (subtitle != null)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text(subtitle!,
                          style: t.bodySmall?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant)),
                    ),
                ]),
              ),
              ?trailing,
            ]),
          if (title != null) const SizedBox(height: 14),
          child,
        ]),
      ),
    );
  }
}

/// A dropdown with a label, for a value from a list.
class LabeledDropdown<T> extends StatelessWidget {
  const LabeledDropdown({
    super.key,
    required this.label,
    required this.value,
    required this.items,
    required this.onChanged,
    this.width = 260,
    this.enabled = true,
  });

  final String label;
  final T value;
  final Map<T, String> items;
  final ValueChanged<T> onChanged;
  final double width;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    final entries = items.entries.toList();
    final has = items.containsKey(value);
    return SizedBox(
      width: width,
      child: InputDecorator(
        decoration: InputDecoration(labelText: label, enabled: enabled, contentPadding: const EdgeInsets.fromLTRB(12, 4, 8, 4)),
        child: DropdownButtonHideUnderline(
          child: DropdownButton<T>(
            isExpanded: true,
            isDense: true,
            value: has ? value : null,
            hint: has ? null : Text('$value'),
            items: [
              for (final e in entries) DropdownMenuItem<T>(value: e.key, child: Text(e.value, overflow: TextOverflow.ellipsis)),
            ],
            onChanged: enabled ? (v) => v == null ? null : onChanged(v) : null,
          ),
        ),
      ),
    );
  }
}

/// A slider with its label and value, reporting when the user lets go.
class SliderRow extends StatefulWidget {
  const SliderRow({
    super.key,
    required this.label,
    required this.value,
    required this.min,
    required this.max,
    required this.onChanged,
    this.format,
    this.divisions,
    this.width = 320,
  });

  final String label;
  final double value;
  final double min;
  final double max;
  final ValueChanged<double> onChanged;
  final String Function(double)? format;
  final int? divisions;
  final double width;

  @override
  State<SliderRow> createState() => _SliderRowState();
}

class _SliderRowState extends State<SliderRow> {
  double? _drag;

  @override
  Widget build(BuildContext context) {
    final v = (_drag ?? widget.value).clamp(widget.min, widget.max).toDouble();
    final text = widget.format?.call(v) ?? v.toStringAsFixed(2);
    return SizedBox(
      width: widget.width,
      child: Row(children: [
        SizedBox(width: 108, child: Text(widget.label, overflow: TextOverflow.ellipsis)),
        Expanded(
          child: Slider(
            value: v,
            min: widget.min,
            max: widget.max,
            divisions: widget.divisions,
            onChanged: (x) => setState(() => _drag = x),
            onChangeEnd: (x) {
              setState(() => _drag = null);
              widget.onChanged(x);
            },
          ),
        ),
        SizedBox(width: 44, child: Text(text, textAlign: TextAlign.right, style: const TextStyle(fontFeatures: []))),
      ]),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({super.key, required this.icon, required this.title, this.message, this.action});

  final IconData icon;
  final String title;
  final String? message;
  final Widget? action;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 36, horizontal: 16),
      child: Column(children: [
        Icon(icon, size: 48, color: cs.primary.withValues(alpha: 0.8)),
        const SizedBox(height: 12),
        Text(title, style: Theme.of(context).textTheme.titleMedium, textAlign: TextAlign.center),
        if (message != null) ...[
          const SizedBox(height: 6),
          Text(message!, textAlign: TextAlign.center, style: TextStyle(color: cs.onSurfaceVariant)),
        ],
        if (action != null) ...[const SizedBox(height: 16), action!],
      ]),
    );
  }
}

/// A small label: "140 BPM", "D#", "2:08" …
class Pill extends StatelessWidget {
  const Pill(this.text, {super.key, this.icon, this.color});

  final String text;
  final IconData? icon;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    final c = color ?? cs.onSurfaceVariant;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: c.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(mainAxisSize: MainAxisSize.min, children: [
        if (icon != null) ...[Icon(icon, size: 14, color: c), const SizedBox(width: 4)],
        Text(text, style: TextStyle(color: c, fontSize: 12.5, fontWeight: FontWeight.w600)),
      ]),
    );
  }
}

/// The video player of a file (the source, a render), with its controls.
class VideoPane extends StatefulWidget {
  const VideoPane({super.key, required this.path, this.aspectRatio = 16 / 9});

  final String? path;
  final double aspectRatio;

  @override
  State<VideoPane> createState() => _VideoPaneState();
}

class _VideoPaneState extends State<VideoPane> {
  Player? _player;
  VideoController? _controller;
  String? _loaded;

  @override
  void initState() {
    super.initState();
    if (Players.enabled) {
      _player = Player();
      _controller = VideoController(_player!);
    }
    _load();
  }

  @override
  void didUpdateWidget(covariant VideoPane oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.path != _loaded) _load();
  }

  void _load() {
    _loaded = widget.path;
    final path = widget.path;
    if (path != null && _player != null) _player!.open(Media(path), play: false);
  }

  @override
  void dispose() {
    _player?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return ClipRRect(
      borderRadius: BorderRadius.circular(12),
      child: AspectRatio(
        aspectRatio: widget.aspectRatio,
        child: Container(
          color: Colors.black,
          child: widget.path == null
              ? Center(child: Icon(Icons.movie_outlined, size: 48, color: cs.onSurfaceVariant))
              : _controller == null
                  ? Center(child: Text(widget.path!.split(RegExp(r'[\\/]')).last, style: const TextStyle(color: Colors.white70)))
                  : Video(controller: _controller!, controls: MaterialVideoControls),
        ),
      ),
    );
  }
}

String fmtTime(num? seconds) {
  final s = (seconds ?? 0).toDouble();
  final m = s ~/ 60;
  final r = s - m * 60;
  return '$m:${r.toStringAsFixed(1).padLeft(4, '0')}';
}

String fmtDuration(num? seconds) {
  final s = (seconds ?? 0).round();
  return '${s ~/ 60}:${(s % 60).toString().padLeft(2, '0')}';
}

/// The parts of a Sparta Remix, as people call them.
const partNames = {
  'intro': 'Intro',
  'intro_hits': 'Intro hits',
  'intro3': 'Intro (3 hits)',
  'chorus': 'Chorus',
  'chorus_final': 'Final Chorus',
  'dundundenden': 'DunDunDenDen',
  'epicness': 'Epicness',
  'chords': 'Chords',
  'awesomeness': 'Awesomeness',
  'awesomeness1': 'Awesomeness 1',
  'awesomeness2': 'Awesomeness 2',
  'madness': 'Madness',
  'execution': 'Execution',
  'ending': 'Ending',
};

/// A colour per part, the same everywhere (timeline, chips).
Color partColor(String kind) {
  if (kind.startsWith('intro')) return const Color(0xFF5B4686);
  if (kind.startsWith('chorus')) return const Color(0xFFB0152F);
  if (kind.startsWith('awesomeness')) return const Color(0xFF2C7A4B);
  return switch (kind) {
    'dundundenden' => const Color(0xFFC0661C),
    'epicness' => const Color(0xFFC79A13),
    'madness' => const Color(0xFF1D5796),
    'execution' => const Color(0xFF74209A),
    'chords' => const Color(0xFF1F7373),
    'ending' => const Color(0xFF4A4A4A),
    _ => const Color(0xFF55606E),
  };
}

/// Text that reads on a part's colour.
Color onPartColor(String kind) => kind == 'epicness' ? const Color(0xFF151100) : Colors.white;

const musicKeys = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
