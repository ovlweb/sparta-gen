import 'package:flutter/material.dart';

import '../../state/app_state.dart';
import '../widgets/common.dart';
import '../widgets/live_preview.dart';

const _choiceNames = <String, Map<String, String>>{
  'flip_mode': {'auto': 'Each track its own', 'none': 'No flips', 'alternate': 'Alternate', 'rotate': 'Rotate', 'mirror': 'Mirror'},
  'hit_anim': {'none': 'None', 'pop': 'Pop', 'slide': 'Slide in'},
  'border': {'none': 'None', 'line': 'Line', 'glow': 'Glow'},
  'color_fx': {'none': 'None', 'hue_cycle': 'New hue every hit', 'invert_crash': 'Invert on crashes', 'mono': 'Mono (all but the phrase)'},
  'tint': {'none': 'None', 'warm': 'Warm', 'cold': 'Cold', 'sepia': 'Sepia', 'vivid': 'Vivid'},
  'transition': {'cut': 'Cut', 'flash': 'Flash', 'fade': 'Fade', 'zoom': 'Zoom'},
  'background': {'blur': 'Blurred video', 'black': 'Black', 'dark': 'Dark', 'mirror': 'Mirrored video', 'gradient': 'Gradient'},
};

const _choiceLabels = {
  'background': 'Background',
  'flip_mode': 'Flips',
  'hit_anim': 'Hit animation',
  'transition': 'Between parts',
  'border': 'Borders',
  'color_fx': 'Colour effect',
  'tint': 'Tint',
};

/// Slider effects: label, max, how the value reads.
const _amounts = <String, (String, double, String)>{
  'punch': ('Zoom punch', 0.12, 'pct'),
  'shake': ('Shake', 1, 'pct'),
  'rgb_split': ('RGB split', 1, 'pct'),
  'scanlines': ('Scanlines', 1, 'pct'),
  'grain': ('Grain', 1, 'pct'),
  'vignette': ('Vignette', 1, 'pct'),
  'letterbox': ('Letterbox', 0.2, 'pct'),
};

/// Everything a style sets — picking a style (or going back to it) clears these.
const _effectKeys = [
  'flip_mode', 'hit_anim', 'border', 'color_fx', 'tint', 'transition', 'background', //
  'punch', 'shake', 'rgb_split', 'scanlines', 'grain', 'vignette', 'letterbox', 'border_color', 'flash', 'hold_last',
];

const _borderColors = {
  'auto': null,
  '#ffffff': Color(0xFFFFFFFF),
  '#e7b62c': Color(0xFFE7B62C),
  '#ff4d5e': Color(0xFFFF4D5E),
  '#3fd0ff': Color(0xFF3FD0FF),
  '#b26bff': Color(0xFFB26BFF),
  '#52e07c': Color(0xFF52E07C),
};

const _fxNames = {
  'reverb': 'Reverb',
  'delay': 'Delay',
  'ott': 'OTT',
  'pump': 'Sidechain pump',
  'drive': 'Drive',
  'width': 'Stereo width',
  'lofi': 'Lo-fi',
};

const _switchNames = {
  'tape_stop_end': 'Tape stop at the end',
  'risers': 'Risers into the big parts',
  'stutter_fills': 'Stutter fills',
};

const _styleIcons = {
  'classic': Icons.grid_view,
  'clean': Icons.crop_square,
  'xleth': Icons.flash_on,
  'retro': Icons.tv,
  'neon': Icons.blur_on,
  'cinematic': Icons.movie_filter,
  'mirror': Icons.flip,
};

const _fxIcons = {
  'xleth': Icons.bolt,
  'clean': Icons.water_drop_outlined,
  'loud': Icons.volume_up,
  'lofi': Icons.radio,
  'big_room': Icons.stadium,
  'retro': Icons.album,
};

class LookPage extends StatelessWidget {
  const LookPage({super.key, required this.app});

  final AppState app;

  @override
  Widget build(BuildContext context) {
    final look = app.look;
    if (look == null) {
      return const Center(child: CircularProgressIndicator());
    }
    const title = 'Look & sound';
    const subtitle = 'How the video moves and how the mix sounds. Start from a style or a sound, then change any '
        'effect — the picture shows it at once. What you choose stays for your next projects too.';
    final controls = [
      _styleCard(context, look),
      _effectsCard(context, look),
      _volumesCard(context, look),
      _soundCard(context, look),
    ];
    return LayoutBuilder(builder: (context, box) {
      if (box.maxWidth < 1100) {
        return PageBody(title: title, subtitle: subtitle, children: [
          LivePreview(app: app),
          ...controls,
          _PreviewCard(app: app),
        ]);
      }
      // Side by side: the picture stays in view while the effects change it.
      return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        SizedBox(
          width: box.maxWidth * 0.46,
          child: ListView(padding: const EdgeInsets.fromLTRB(24, 20, 8, 32), children: [
            LivePreview(app: app),
            const SizedBox(height: 16),
            _PreviewCard(app: app),
          ]),
        ),
        Expanded(child: PageBody(title: title, subtitle: subtitle, children: controls)),
      ]);
    });
  }

  static String _db(double v) {
    final t = v.toStringAsFixed(v == v.roundToDouble() ? 0 : 1);
    return v > 0 ? '+$t dB' : '$t dB';
  }

  Widget _volumesCard(BuildContext context, Map<String, dynamic> look) {
    final groups = _m(look['volume_groups']);
    final range = (look['volume_range'] as List?) ?? const [-24, 12];
    final lo = (range[0] as num).toDouble();
    final hi = (range[1] as num).toDouble();
    final vols = app.volumes;
    final muted = app.mutedGroups;
    final mix = _m(look['mix']);
    final enabled = !app.busy;
    final changed = vols.values.any((v) => (v as num) != 0) || muted.isNotEmpty;
    return SectionCard(
      title: 'Volumes',
      subtitle: 'How loud each part is. A part you switch off is out of the video too.',
      trailing: changed
          ? TextButton.icon(
              onPressed: enabled ? app.resetVolumes : null,
              icon: const Icon(Icons.restart_alt),
              label: const Text('All back to 0 dB'),
            )
          : null,
      child: Wrap(spacing: 24, runSpacing: 2, children: [
        if (look['has_base'] == true)
          Row(mainAxisSize: MainAxisSize.min, children: [
            const Padding(padding: EdgeInsets.all(12), child: Icon(Icons.album_outlined)),
            SliderRow(
              label: 'Your base',
              value: ((mix['base_gain_db'] as num?) ?? -3).toDouble(),
              min: -24,
              max: 6,
              divisions: 60,
              width: 300,
              format: _db,
              onChanged: (v) => app.baseOptions({'base_gain_db': double.parse(v.toStringAsFixed(1))}),
            ),
          ]),
        for (final e in groups.entries)
          Row(mainAxisSize: MainAxisSize.min, children: [
            IconButton(
              tooltip: muted.contains(e.key) ? 'Switch ${e.value} on' : 'Switch ${e.value} off',
              isSelected: !muted.contains(e.key),
              icon: const Icon(Icons.volume_off),
              selectedIcon: const Icon(Icons.volume_up),
              onPressed: enabled ? () => app.muteGroup(e.key, !muted.contains(e.key)) : null,
            ),
            Opacity(
              opacity: muted.contains(e.key) ? 0.45 : 1,
              child: SliderRow(
                label: '${e.value}',
                value: ((vols[e.key] as num?) ?? 0).toDouble(),
                min: lo,
                max: hi,
                divisions: ((hi - lo) * 2).round(),
                width: 300,
                format: _db,
                onChanged: (v) => app.setVolume(e.key, v),
              ),
            ),
          ]),
      ]),
    );
  }

  Map<String, dynamic> _m(dynamic v) => v is Map ? v.cast<String, dynamic>() : {};

  Widget _styleCard(BuildContext context, Map<String, dynamic> look) {
    final styles = _m(look['styles']);
    final video = _m(look['video']);
    final current = '${video['style'] ?? 'classic'}';
    return SectionCard(
      title: 'Visual style',
      subtitle: 'Picking a style sets all its effects; your own changes start over.',
      child: Wrap(spacing: 10, runSpacing: 10, children: [
        for (final e in styles.entries)
          ChoiceChip(
            avatar: Icon(_styleIcons[e.key] ?? Icons.auto_awesome, size: 18),
            label: Text('${e.value}'),
            selected: e.key == current,
            onSelected: app.busy
                ? null
                : (_) => app.setLook(video: {'style': e.key, for (final k in _effectKeys) k: null}),
          ),
      ]),
    );
  }

  Widget _effectsCard(BuildContext context, Map<String, dynamic> look) {
    final video = _m(look['video']);
    final set = _m(look['video_set']);
    final options = _m(look['style_options']);
    final changed = set.keys.where(_effectKeys.contains).length;
    final enabled = !app.busy;
    return SectionCard(
      title: 'Effects',
      subtitle: changed == 0 ? 'As the style has them.' : '$changed changed by you.',
      trailing: changed == 0
          ? null
          : TextButton.icon(
              onPressed: enabled
                  ? () => app.setLook(video: {'style': video['style'], for (final k in _effectKeys) k: null})
                  : null,
              icon: const Icon(Icons.restart_alt),
              label: const Text('Back to the style'),
            ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 14, runSpacing: 14, children: [
          for (final k in _choiceLabels.keys)
            if (options[k] is List)
              LabeledDropdown<String>(
                label: _choiceLabels[k]!,
                width: 220,
                enabled: enabled,
                value: '${video[k]}',
                items: {for (final c in (options[k] as List)) '$c': _choiceNames[k]?['$c'] ?? '$c'},
                onChanged: (v) => app.setLook(video: {k: v}),
              ),
        ]),
        const SizedBox(height: 16),
        Wrap(spacing: 24, runSpacing: 4, children: [
          for (final e in _amounts.entries)
            SliderRow(
              label: e.value.$1,
              value: ((video[e.key] as num?) ?? 0).toDouble(),
              min: 0,
              max: e.value.$2,
              divisions: 40,
              format: (v) => '${(v / e.value.$2 * 100).round()}%',
              onChanged: (v) => app.setLook(video: {e.key: double.parse(v.toStringAsFixed(3))}),
            ),
        ]),
        const SizedBox(height: 10),
        Wrap(spacing: 24, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
          _switch('Flash on the big hits', video['flash'] == true, enabled, (v) => app.setLook(video: {'flash': v})),
          _switch('Keep the last clip (dimmed)', video['hold_last'] == true, enabled,
              (v) => app.setLook(video: {'hold_last': v})),
          Row(mainAxisSize: MainAxisSize.min, children: [
            const Text('Border colour'),
            const SizedBox(width: 10),
            for (final e in _borderColors.entries)
              Padding(
                padding: const EdgeInsets.only(right: 6),
                child: _Swatch(
                  color: e.value,
                  selected: '${video['border_color']}'.toLowerCase() == e.key,
                  onTap: enabled ? () => app.setLook(video: {'border_color': e.key}) : null,
                ),
              ),
          ]),
        ]),
      ]),
    );
  }

  Widget _soundCard(BuildContext context, Map<String, dynamic> look) {
    final presets = _m(look['fx_presets']);
    final amounts = _m(look['fx_amounts']);
    final switches = _m(look['fx_switches']);
    final mix = _m(look['mix']);
    final set = _m(look['mix_set']);
    final current = '${mix['fx_preset'] ?? 'xleth'}';
    final changed = set.keys.where((k) => amounts.containsKey(k) || switches.containsKey(k)).length;
    final enabled = !app.busy;
    return SectionCard(
      title: 'Sound',
      subtitle: 'The FX over the whole mix. ${changed == 0 ? 'As the preset has them.' : '$changed changed by you.'}',
      trailing: changed == 0
          ? null
          : TextButton.icon(
              onPressed: enabled ? () => app.setLook(mix: {'fx_preset': current}, replaceFx: true) : null,
              icon: const Icon(Icons.restart_alt),
              label: const Text('Back to the preset'),
            ),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 10, runSpacing: 10, children: [
          for (final e in presets.entries)
            ChoiceChip(
              avatar: Icon(_fxIcons[e.key] ?? Icons.graphic_eq, size: 18),
              label: Text('${e.value}'),
              selected: e.key == current,
              onSelected: enabled ? (_) => app.setLook(mix: {'fx_preset': e.key}, replaceFx: true) : null,
            ),
        ]),
        const SizedBox(height: 16),
        Wrap(spacing: 24, runSpacing: 4, children: [
          for (final e in amounts.entries)
            SliderRow(
              label: _fxNames[e.key] ?? e.key,
              value: ((mix[e.key] as num?) ?? (e.value as Map)['default'] as num).toDouble(),
              min: ((e.value as Map)['min'] as num).toDouble(),
              max: ((e.value as Map)['max'] as num).toDouble(),
              divisions: 40,
              format: (v) => '${(v * 100).round()}%',
              onChanged: (v) => app.setLook(mix: {e.key: double.parse(v.toStringAsFixed(3))}),
            ),
        ]),
        const SizedBox(height: 10),
        Wrap(spacing: 24, runSpacing: 8, children: [
          for (final k in switches.keys)
            _switch(_switchNames[k] ?? k, mix[k] == true, enabled, (v) => app.setLook(mix: {k: v})),
        ]),
      ]),
    );
  }

  Widget _switch(String label, bool value, bool enabled, ValueChanged<bool> onChanged) => Row(
        mainAxisSize: MainAxisSize.min,
        children: [Switch(value: value, onChanged: enabled ? onChanged : null), const SizedBox(width: 6), Text(label)],
      );
}

class _Swatch extends StatelessWidget {
  const _Swatch({required this.color, required this.selected, this.onTap});

  final Color? color;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Tooltip(
      message: color == null ? 'The part’s own colour' : '#${color!.toARGB32().toRadixString(16).substring(2)}',
      child: InkWell(
        onTap: onTap,
        customBorder: const CircleBorder(),
        child: Container(
          width: 26,
          height: 26,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: color,
            gradient: color == null
                ? const SweepGradient(colors: [Color(0xFFB0152F), Color(0xFFC79A13), Color(0xFF2C7A4B), Color(0xFF1D5796), Color(0xFFB0152F)])
                : null,
            border: Border.all(color: selected ? cs.primary : cs.outlineVariant, width: selected ? 3 : 1),
          ),
        ),
      ),
    );
  }
}

class _PreviewCard extends StatelessWidget {
  const _PreviewCard({required this.app});

  final AppState app;

  @override
  Widget build(BuildContext context) {
    final can = app.hasSource && !app.busy;
    final pane = VideoPane(path: app.lastRender);
    final info = Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(app.lastRender == null ? 'No preview yet' : 'The last render',
          style: Theme.of(context).textTheme.titleMedium),
      const SizedBox(height: 6),
      Text(
        'A quick low-resolution render shows the look and the sound together. It takes about a minute.',
        style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant),
      ),
      const SizedBox(height: 14),
      FilledButton.icon(
        onPressed: can ? () => app.render('preview') : null,
        icon: const Icon(Icons.play_circle_outline),
        label: const Text('Render a preview'),
      ),
      if (!app.hasSource)
        Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Text('Open a video first.', style: TextStyle(color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ),
    ]);
    return SectionCard(
      child: LayoutBuilder(builder: (context, box) {
        if (box.maxWidth > 760) {
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            SizedBox(width: box.maxWidth * 0.5, child: pane),
            const SizedBox(width: 20),
            Expanded(child: info),
          ]);
        }
        return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [pane, const SizedBox(height: 14), info]);
      }),
    );
  }
}
