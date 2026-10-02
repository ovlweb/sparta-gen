import 'package:flutter/material.dart';

import '../../platform/files.dart';
import '../../state/app_state.dart';
import '../widgets/common.dart';

class BasePage extends StatefulWidget {
  const BasePage({super.key, required this.app});

  final AppState app;

  @override
  State<BasePage> createState() => _BasePageState();
}

class _BasePageState extends State<BasePage> {
  String? _mode; // template | audio | midi
  String _search = '';
  String _baseTemplate = '';
  final Map<String, String> _lastRole = {};

  AppState get app => widget.app;

  String get mode {
    if (_mode != null) return _mode!;
    if (app.variant == 'midi') return app.templateId.isNotEmpty ? 'template' : 'midi';
    if (app.variant == 'base') return app.templateId.isNotEmpty ? 'template' : 'audio';
    if (app.baseMap != null) return 'audio';
    return 'template';
  }

  @override
  Widget build(BuildContext context) {
    return PageBody(
      title: 'Base',
      subtitle: 'What your remix is built on: a base template, your base’s audio file, or its MIDI (for bases that '
          'are not public). Chorus, percussion and the other parts work the same on every base.',
      children: [
        Center(
          child: SegmentedButton<String>(
            segments: [
              for (final (value, icon, words) in const [
                ('template', Icons.dashboard_customize_outlined, 'Template'),
                ('audio', Icons.audio_file_outlined, 'Base audio file'),
                ('midi', Icons.piano, 'MIDI'),
              ])
                ButtonSegment(
                    value: value, icon: Icon(icon), tooltip: words, label: iconButtons(context) ? null : Text(words)),
            ],
            selected: {mode},
            onSelectionChanged: (s) => setState(() => _mode = s.first),
          ),
        ),
        if (mode == 'template') ..._templateMode(context),
        if (mode == 'audio') ..._audioMode(context),
        if (mode == 'midi') ..._midiMode(context),
        _keyCard(context),
      ],
    );
  }

  // ── templates ──

  List<Map<String, dynamic>> get _groups {
    final g = app.catalog?['groups'];
    return g is List ? g.map((e) => (e as Map).cast<String, dynamic>()).toList() : [];
  }

  List<Widget> _templateMode(BuildContext context) {
    final current = app.template;
    final selectedId = app.templateId;
    final list = SectionCard(
      title: 'Base templates',
      subtitle: 'The Sparta Remix’s own base, four MIDI bases whose notes the samples play, and yours.',
      child: Column(children: [
        TextField(
          decoration: const InputDecoration(labelText: 'Search', prefixIcon: Icon(Icons.search)),
          onChanged: (v) => setState(() => _search = v.trim().toLowerCase()),
        ),
        const SizedBox(height: 10),
        SizedBox(
          height: 460,
          child: ListView(children: [
            for (final g in _groups) ..._groupTiles(context, g, selectedId),
          ]),
        ),
      ]),
    );
    final details = current != null
        ? _templateDetails(context, current)
        : SectionCard(
            child: EmptyState(
              icon: Icons.touch_app_outlined,
              title: 'Pick a template to build the remix on it',
              message: app.variant == 'midi'
                  ? 'The remix follows your MIDI base now.'
                  : app.variant == 'base'
                      ? 'The remix follows your base’s audio file now.'
                      : null,
            ),
          );
    final basePath = app.basePath;
    return [
      if (basePath != null && !app.baseHeard)
        Card(
          color: Theme.of(context).colorScheme.secondary.withValues(alpha: 0.12),
          child: ListTile(
            leading: Icon(Icons.info_outline, color: Theme.of(context).colorScheme.secondary),
            title: Text('Your base ${basePath.split(RegExp(r'[\\/]')).last} is silent while the remix is built on a '
                'template.'),
            trailing: TextButton(
              onPressed: app.busy ? null : () => app.baseOptions({'follow': true}),
              child: const Text('Build it on my base'),
            ),
          ),
        ),
      LayoutBuilder(builder: (context, box) {
        if (box.maxWidth > 900) {
          return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(flex: 5, child: list),
            const SizedBox(width: 16),
            Expanded(flex: 6, child: details),
          ]);
        }
        return Column(children: [list, const SizedBox(height: 16), details]);
      }),
    ];
  }

  List<Widget> _groupTiles(BuildContext context, Map<String, dynamic> g, String selectedId) {
    final ts = (g['templates'] as List).map((e) => (e as Map).cast<String, dynamic>()).where((t) {
      if (_search.isEmpty) return true;
      return '${t['name']} ${t['description']} ${t['key']}'.toLowerCase().contains(_search);
    }).toList();
    if (ts.isEmpty && !(g['name'] == 'My templates' && _search.isEmpty)) return [];
    final cs = Theme.of(context).colorScheme;
    return [
      Padding(
        padding: const EdgeInsets.fromLTRB(8, 12, 8, 4),
        child: Text('${g['name']}'.toUpperCase(),
            style: TextStyle(fontSize: 12, letterSpacing: 1.1, fontWeight: FontWeight.w700, color: cs.secondary)),
      ),
      if (ts.isEmpty)
        Padding(
          padding: const EdgeInsets.all(8),
          child: Text('Save a structure or import a .spartabase.json to see it here.',
              style: TextStyle(color: cs.onSurfaceVariant)),
        ),
      for (final t in ts)
        ListTile(
          dense: true,
          selected: t['id'] == selectedId,
          selectedTileColor: cs.primary.withValues(alpha: 0.12),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          leading: Icon(
              t['user'] == true ? Icons.person_outline : ('${t['midi'] ?? ''}' != '' ? Icons.piano : Icons.queue_music),
              size: 20),
          title: Text('${t['name']}'),
          subtitle: Text('${_bpm(t)} · ${t['key']}${t['minor'] == true ? 'm' : ''} · ${t['bars']} bars · '
              '${fmtDuration(t['duration'] as num?)}'),
          onTap: app.busy ? null : () => app.useTemplate('${t['id']}'),
        ),
    ];
  }

  String _bpm(Map t) {
    final b = (t['bpm'] as num).toDouble();
    return '${b.toStringAsFixed(b == b.roundToDouble() ? 0 : 1)}${t['bpm_known'] == false ? '?' : ''} BPM';
  }

  Widget _templateDetails(BuildContext context, Map<String, dynamic> t) {
    final cs = Theme.of(context).colorScheme;
    final opts = (app.project['options'] as Map?) ?? {};
    final bpmCtrl = TextEditingController(text: '${opts['bpm'] ?? t['bpm']}');
    final plan = (t['plan'] as List).map((e) => (e as List)).toList();
    final isMidi = '${t['midi'] ?? ''}' != '';
    final hasAudio = '${t['audio'] ?? ''}' != '';          // it comes with its base: the remix plays on it
    return SectionCard(
      title: '${t['name']}',
      subtitle: '${t['group']}',
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Wrap(spacing: 8, runSpacing: 8, children: [
          if (isMidi) const Pill('MIDI base', icon: Icons.piano),
          if (hasAudio) const Pill('Its base plays under the remix', icon: Icons.graphic_eq),
          Pill(_bpm(t), icon: Icons.speed),
          Pill('Key ${t['key']}${t['minor'] == true ? ' minor' : ''}', icon: Icons.music_note),
          Pill('${t['bars']} bars', icon: Icons.view_week),
          Pill(fmtDuration(t['duration'] as num?), icon: Icons.schedule),
        ]),
        const SizedBox(height: 12),
        Text('${t['description']}'),
        if ((t['credit'] ?? '') != '') ...[
          const SizedBox(height: 6),
          Text('Base by ${t['credit']}', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12.5)),
        ],
        if (isMidi && app.templateId == t['id']) ...[
          const SizedBox(height: 10),
          AdaptiveButton.text(
            onPressed: () => setState(() => _mode = 'midi'),
            icon: const Icon(Icons.tune),
            label: const Text('What the samples play of each instrument…'),
          ),
        ],
        const SizedBox(height: 14),
        Text('Parts', style: Theme.of(context).textTheme.titleSmall),
        const SizedBox(height: 6),
        Wrap(spacing: 6, runSpacing: 6, children: [
          for (final part in plan)
            Chip(
              visualDensity: VisualDensity.compact,
              avatar: _dot('${part[0]}'),
              label: Text('${partNames[part[0]] ?? part[0]} · ${part[1]}'),
            ),
        ]),
        if (!isMidi && !hasAudio) ...[                       // (a base's own audio keeps its tempo)
          const SizedBox(height: 16),
          Row(children: [
            SizedBox(
              width: 150,
              child: TextField(
                controller: bpmCtrl,
                decoration: const InputDecoration(labelText: 'Tempo (BPM)'),
                keyboardType: const TextInputType.numberWithOptions(decimal: true),
                onSubmitted: (v) {
                  final b = double.tryParse(v.replaceAll(',', '.'));
                  if (b != null && b >= 40 && b <= 300) app.useTemplate('${t['id']}', options: {'bpm': b});
                },
              ),
            ),
            const SizedBox(width: 10),
            Flexible(
              child:
                  Text('Press Enter to use another tempo.', style: TextStyle(color: cs.onSurfaceVariant, fontSize: 12.5)),
            ),
          ]),
        ],
        const SizedBox(height: 16),
        Wrap(spacing: 10, runSpacing: 10, children: [
          AdaptiveButton.outlined(
            onPressed: () => _saveTemplateDialog(context),
            icon: const Icon(Icons.save_outlined),
            label: const Text('Save current structure as my template…'),
          ),
          AdaptiveButton.outlined(
            onPressed: () async {
              final path = await app.pickFile(Kinds.json);
              if (path != null) await app.importTemplate(path);
            },
            icon: const Icon(Icons.file_download_outlined),
            label: const Text('Import template…'),
          ),
          if (t['user'] == true)
            AdaptiveButton.text(
              onPressed: () async {
                await app.deleteTemplate('${t['id']}');
                await app.useTemplate('extended');
              },
              icon: const Icon(Icons.delete_outline),
              label: const Text('Delete'),
            ),
        ]),
      ]),
    );
  }

  Future<void> _saveTemplateDialog(BuildContext context) async {
    final name = TextEditingController();
    final desc = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Save as my template'),
        content: SizedBox(
          width: 420,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            TextField(controller: name, autofocus: true, decoration: const InputDecoration(labelText: 'Base name')),
            const SizedBox(height: 12),
            TextField(controller: desc, decoration: const InputDecoration(labelText: 'Notes (optional)'), maxLines: 2),
            const SizedBox(height: 8),
            const Text('Saves the parts, tempo, key and pattern choices of the current remix. The file '
                '(.spartabase.json) can be shared and imported by other remixers.'),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('Save')),
        ],
      ),
    );
    if (ok == true && name.text.trim().isNotEmpty) await app.saveTemplate(name.text.trim(), desc.text.trim());
  }

  Map<String, String> get _templateChoices {
    final out = <String, String>{'': 'Auto — read everything from the file'};
    for (final g in _groups) {
      for (final t in (g['templates'] as List)) {
        final m = (t as Map);
        out['${m['id']}'] = '${m['name']}';
      }
    }
    return out;
  }

  // ── base audio ──

  List<Widget> _audioMode(BuildContext context) {
    final bm = app.baseMap;
    final path = app.basePath;
    final cs = Theme.of(context).colorScheme;
    if (path == null) {
      return [
        SectionCard(
          child: Column(children: [
            EmptyState(
              icon: Icons.audio_file_outlined,
              title: 'Open your Sparta base (mp3, wav …)',
              message: 'Its tempo, bar 1, key, chords and parts (Chorus, DunDunDenDen, Epicness, Madness …) are read '
                  'from it and the remix is built bar for bar on them.',
              action: AdaptiveButton.filled(
                onPressed: app.busy ? null : () => _openBase(),
                icon: const Icon(Icons.folder_open),
                label: const Text('Open base audio…'),
              ),
            ),
            LabeledDropdown<String>(
              label: 'This base is (optional)',
              value: _baseTemplate,
              width: 420,
              items: _templateChoices,
              onChanged: (v) => setState(() => _baseTemplate = v),
            ),
          ]),
        ),
      ];
    }
    final mix = (app.project['mix'] as Map?) ?? {};
    final sections = (bm?['sections'] as List?)?.map((e) => (e as Map).cast<String, dynamic>()).toList() ?? [];
    return [
      SectionCard(
        title: path.split(RegExp(r'[\\/]')).last,
        subtitle: bm == null ? 'Plays under the remix (its parts could not be read)' : 'Read from the file',
        trailing: AdaptiveButton.text(
            onPressed: app.busy ? null : app.clearBase, icon: const Icon(Icons.close), label: const Text('Remove')),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (bm != null)
            Wrap(spacing: 8, runSpacing: 8, children: [
              Pill('${((bm['bpm'] as num?) ?? 0).toStringAsFixed(2)} BPM', icon: Icons.speed),
              Pill('Key ${app.key}${bm['minor'] == true ? ' minor' : ''}', icon: Icons.music_note),
              Pill('${bm['bars']} bars', icon: Icons.view_week),
              Pill('bar 1 at ${((bm['offset'] as num?) ?? 0).toStringAsFixed(3)} s', icon: Icons.flag_outlined),
              Pill('chords ${bm['progression'] ?? ''}', icon: Icons.piano),
            ]),
          if (sections.isNotEmpty) ...[
            const SizedBox(height: 14),
            Text('Its parts', style: Theme.of(context).textTheme.titleSmall),
            const SizedBox(height: 6),
            Wrap(spacing: 6, runSpacing: 6, children: [
              for (final s in sections)
                Chip(
                  visualDensity: VisualDensity.compact,
                  avatar: _dot('${s['kind']}'),
                  label: Text('${partNames[s['kind']] ?? s['kind']} · ${s['bars']}'),
                ),
            ]),
          ],
          const SizedBox(height: 16),
          Wrap(spacing: 16, runSpacing: 16, crossAxisAlignment: WrapCrossAlignment.center, children: [
            LabeledDropdown<String>(
              label: 'This base is',
              value: '${app.project['base_template'] ?? ''}',
              width: 360,
              items: _templateChoices,
              onChanged: (v) => app.baseOptions({'template': v}),
            ),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'detected', label: Text('Its detected parts')),
                ButtonSegment(value: 'template', label: Text('The template’s layout')),
              ],
              selected: {'${app.project['base_structure'] ?? 'detected'}'},
              onSelectionChanged: (s) => app.baseOptions({'structure': s.first}),
            ),
          ]),
          const SizedBox(height: 12),
          Wrap(spacing: 16, runSpacing: 8, crossAxisAlignment: WrapCrossAlignment.center, children: [
            SliderRow(
              label: 'Base volume',
              value: ((mix['base_gain_db'] as num?) ?? -3).toDouble(),
              min: -24,
              max: 6,
              divisions: 30,
              format: (v) => '${v.toStringAsFixed(0)} dB',
              onChanged: app.setBaseVolume,
            ),
            LabeledDropdown<String>(
              label: 'Our drums and bass',
              value: '${mix['base_mode'] ?? 'remix'}',
              width: 330,
              items: const {
                'remix': 'Keep them over the base (remix)',
                'replace': 'Leave them to the base (replace)',
                'layer': 'Keep everything (layer)',
              },
              onChanged: (v) => app.baseOptions({'base_mode': v}),
            ),
          ]),
          const SizedBox(height: 14),
          Wrap(spacing: 10, runSpacing: 10, children: [
            if (app.variant != 'base' && bm != null)
              AdaptiveButton.filled(
                onPressed: () => app.baseOptions({'follow': true}),
                icon: const Icon(Icons.check),
                label: const Text('Build the remix on this base'),
              ),
            AdaptiveButton.outlined(
                onPressed: app.busy ? null : () => _openBase(),
                icon: const Icon(Icons.folder_open),
                label: const Text('Open another base…')),
          ]),
          if (app.variant == 'midi' && app.baseHeard)
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text('The remix follows the MIDI; this file plays under it.',
                  style: TextStyle(color: cs.onSurfaceVariant)),
            )
          else if (app.variant != 'base')
            Padding(
              padding: const EdgeInsets.only(top: 10),
              child: Text('The remix is built on a template now, so this file is silent — build the remix on it to '
                  'hear it under the remix again.',
                  style: TextStyle(color: cs.onSurfaceVariant)),
            ),
        ]),
      ),
    ];
  }

  Future<void> _openBase({bool follow = true}) async {
    final path = await app.pickFile(Kinds.audio);
    if (path == null) return;
    await app.openBase(path, template: _baseTemplate, follow: follow);
  }

  // ── MIDI ──

  List<Widget> _midiMode(BuildContext context) {
    final m = app.midi;
    if (m == null) {
      return [
        SectionCard(
          child: EmptyState(
            icon: Icons.piano,
            title: 'Open the MIDI of your base',
            message: 'Any base, even one that is not public: each MIDI channel becomes a part of the remix — the main '
                'phrase, a pitch, the chords, the bass, the drums … — or you switch it off.',
            action: AdaptiveButton.filled(
              onPressed: app.busy ? null : _openMidi,
              icon: const Icon(Icons.folder_open),
              label: const Text('Open MIDI…'),
            ),
          ),
        ),
      ];
    }
    final s = (m['summary'] as Map).cast<String, dynamic>();
    final mapping = (m['mapping'] as Map).cast<String, dynamic>();
    final roles = (m['roles'] as Map).cast<String, dynamic>().map((k, v) => MapEntry(k, '$v'.split(' (').first));
    final parts = (s['parts'] as List).map((e) => (e as Map).cast<String, dynamic>()).toList();
    final warnings = (s['warnings'] as List?) ?? [];
    final cs = Theme.of(context).colorScheme;
    return [
      SectionCard(
        title: '${s['path']}'.split(RegExp(r'[\\/]')).last,
        subtitle: app.variant == 'midi' ? 'The remix plays these notes' : 'Loaded — not used by the remix yet',
        trailing: AdaptiveButton.text(
            onPressed: app.busy ? null : app.clearMidi, icon: const Icon(Icons.close), label: const Text('Remove')),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Wrap(spacing: 8, runSpacing: 8, children: [
            Pill('${((s['bpm'] as num?) ?? 0).toStringAsFixed(2)} BPM', icon: Icons.speed),
            Pill('Key ${s['key']}${s['minor'] == true ? ' minor' : ''}', icon: Icons.music_note),
            Pill('${s['bars']} bars', icon: Icons.view_week),
            Pill('${s['notes']} notes', icon: Icons.piano),
            Pill(fmtDuration(s['duration'] as num?), icon: Icons.schedule),
          ]),
          for (final w in warnings)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Row(children: [
                Icon(Icons.info_outline, size: 16, color: cs.secondary),
                const SizedBox(width: 6),
                Expanded(child: Text('$w', style: TextStyle(color: cs.onSurfaceVariant))),
              ]),
            ),
          const SizedBox(height: 16),
          Text('Channels', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 6),
          for (final part in parts) _partRow(context, part, mapping, roles, parts),
          const Divider(height: 28),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: m['auto_percussion'] != false,
            onChanged: (v) => app.midiMapping(autoPercussion: v),
            title: const Text('Add Sparta percussion when no channel plays drums'),
            subtitle: const Text('Kick, snare, two hi-hats and a snare line from your video: Sparta Percussion.'),
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            value: m['auto_phrase'] != false,
            onChanged: (v) => app.midiMapping(autoPhrase: v),
            title: const Text('Put the main phrase on the Chorus pattern'),
            subtitle: const Text('If no channel plays it, it comes in with the base’s Chorus, in each part’s pattern.'),
          ),
          const SizedBox(height: 8),
          Wrap(spacing: 16, runSpacing: 10, crossAxisAlignment: WrapCrossAlignment.center, children: [
            LabeledDropdown<int>(
              label: 'Longest part',
              value: (m['section_bars'] as num?)?.toInt() ?? 8,
              width: 180,
              items: const {4: '4 bars', 8: '8 bars', 16: '16 bars', 32: '32 bars'},
              onChanged: (v) => app.midiMapping(sectionBars: v),
            ),
            if (app.variant != 'midi')
              AdaptiveButton.filled(
                onPressed: () => app.midiMapping(use: true),
                icon: const Icon(Icons.check),
                label: const Text('Build the remix on this MIDI'),
              ),
            AdaptiveButton.outlined(
              onPressed: app.busy ? null : _openMidi,
              icon: const Icon(Icons.folder_open),
              label: const Text('Open another MIDI…'),
            ),
          ]),
        ]),
      ),
      SectionCard(
        title: 'Backing audio (optional)',
        subtitle: 'Play the base’s own audio under the MIDI remix — its bar 1 on the MIDI’s first beat.',
        child: Wrap(spacing: 10, runSpacing: 10, crossAxisAlignment: WrapCrossAlignment.center, children: [
          if (app.basePath != null) Pill(app.basePath!.split(RegExp(r'[\\/]')).last, icon: Icons.audio_file_outlined),
          AdaptiveButton.outlined(
            onPressed: app.busy ? null : () => _openBase(follow: false),
            icon: const Icon(Icons.audio_file_outlined),
            label: Text(app.basePath == null ? 'Add base audio…' : 'Change…'),
          ),
          if (app.basePath != null)
            TextButton(
              onPressed: app.clearBase,
              child: const Text('Remove'),
            ),
        ]),
      ),
    ];
  }

  Future<void> _openMidi() async {
    final path = await app.pickFile(Kinds.midi);
    if (path != null) await app.openMidi(path);
  }

  Widget _partRow(BuildContext context, Map<String, dynamic> part, Map<String, dynamic> mapping,
      Map<String, String> roles, List<Map<String, dynamic>> parts) {
    final id = '${part['id']}';
    // A channel playing another's notes (a base layering one line twice) starts off: say which.
    final twin = parts.where((p) => p['id'] == part['double_of']).map((p) => '${p['name']}').firstOrNull;
    final m = (mapping[id] as Map?)?.cast<String, dynamic>() ?? {'role': 'off'};
    final role = '${m['role']}';
    final octave = (m['octave'] as num?)?.toInt() ?? 0;
    final gain = (m['gain_db'] as num?)?.toDouble() ?? 0;
    final on = role != 'off';
    final cs = Theme.of(context).colorScheme;
    // A channel's whole setting, with one thing changed (the engine replaces a channel's setting whole).
    void change({String? r, int? oct, double? db}) =>
        app.midiMapping(mapping: {id: {'role': r ?? role, 'octave': oct ?? octave, 'gain_db': db ?? gain}});
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Wrap(spacing: 12, runSpacing: 6, crossAxisAlignment: WrapCrossAlignment.center, children: [
        Switch(
          value: on,
          onChanged: (v) {
            if (!v) {
              _lastRole[id] = role;
              change(r: 'off');
            } else {
              change(r: _lastRole[id] ?? (part['drums'] == true ? 'drums' : 'pitch2'));
            }
          },
        ),
        SizedBox(
          width: 220,
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('${part['name']}', overflow: TextOverflow.ellipsis,
                style: TextStyle(fontWeight: FontWeight.w600, color: on ? null : cs.onSurfaceVariant)),
            Text('ch ${part['channel']} · ${part['notes']} notes · ${part['range']}'
                '${(part['polyphony'] as num? ?? 1) > 1 ? ' · chords' : ''}${twin != null ? ' · doubles $twin' : ''}',
                style: TextStyle(fontSize: 12, color: cs.onSurfaceVariant)),
          ]),
        ),
        LabeledDropdown<String>(
          label: 'Plays',
          value: role,
          width: 250,
          items: roles,
          onChanged: (v) => change(r: v),
        ),
        if (on && part['drums'] != true)
          Row(mainAxisSize: MainAxisSize.min, children: [
            IconButton(
              tooltip: 'Octave down',
              onPressed: octave <= -3 ? null : () => change(oct: octave - 1),
              icon: const Icon(Icons.remove_circle_outline),
            ),
            Text('octave ${octave >= 0 ? '+' : ''}$octave'),
            IconButton(
              tooltip: 'Octave up',
              onPressed: octave >= 3 ? null : () => change(oct: octave + 1),
              icon: const Icon(Icons.add_circle_outline),
            ),
          ]),
        if (on)
          SliderRow(
            label: 'Volume',
            value: gain,
            min: -24,
            max: 12,
            divisions: 36,
            width: 280,
            format: (v) => '${v > 0 ? '+' : ''}${v.toStringAsFixed(0)} dB',
            onChanged: (v) => change(db: v.roundToDouble()),
          ),
      ]),
    );
  }

  // ── key ──

  Widget _keyCard(BuildContext context) {
    final auto = app.keyMode != 'manual';
    return SectionCard(
      title: 'Key',
      subtitle: 'The pitch samples are tuned to it. Auto follows the base (template, audio or MIDI).',
      child: Row(children: [
        LabeledDropdown<String>(
          label: 'Tune the pitches to',
          value: auto ? 'auto' : app.key,
          width: 280,
          items: {'auto': 'Auto — ${app.key}', for (final k in musicKeys) k: k},
          onChanged: app.setKey,
        ),
      ]),
    );
  }

  /// The part's colour, as on the Remix page's timeline.
  static Widget _dot(String kind) => Container(
        width: 10,
        height: 10,
        decoration: BoxDecoration(color: partColor(kind), shape: BoxShape.circle),
      );
}
