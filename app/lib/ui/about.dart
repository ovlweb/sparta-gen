import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import 'theme.dart';

const krasenChannel = 'https://www.youtube.com/c/CassidyBOTRR';
const krasenGithub = 'https://github.com/composition-cassidy';
const xlethUrl = 'https://github.com/composition-cassidy/Xleth';
const wikiUrl = 'https://spartaremix.fandom.com/wiki/Sparta_Remix_Wiki';

/// SpartaGen's own terms: it belongs to everyone, not to the people who wrote it.
const publicDomain = 'No copyright: SpartaGen is public domain (The Unlicense). It belongs to everyone — use, change, '
    'share or sell it, no permission needed. The parts made by others keep their own licences (see Licenses).';

Future<void> openLink(String url) async {
  try {
    await launchUrl(Uri.parse(url), mode: LaunchMode.externalApplication);
  } catch (_) {}
}

class AppLogo extends StatelessWidget {
  const AppLogo({super.key, this.size = 48});

  final double size;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(size * 0.22),
        boxShadow: [BoxShadow(color: spartaRed.withValues(alpha: 0.30), blurRadius: size * 0.22)],
      ),
      child: Image.asset('assets/icon.png', width: size, height: size, filterQuality: FilterQuality.medium),
    );
  }
}

Future<void> showAbout(BuildContext context, {required String version}) {
  return showDialog(
    context: context,
    builder: (context) {
      final cs = Theme.of(context).colorScheme;
      final t = Theme.of(context).textTheme;
      return AlertDialog(
        title: Row(children: [
          const AppLogo(size: 44),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('SpartaGen'),
              Text('Version $version · release candidate', style: t.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
            ]),
          ),
        ]),
        content: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 460),
          child: SingleChildScrollView(
            child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
              const Text('A real Sparta Remix generator: it cuts the samples from your video, tunes the pitches to '
                  'your base, and builds the remix with the patterns the Sparta Remix community uses.'),
              const SizedBox(height: 16),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: cs.secondary.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: cs.secondary.withValues(alpha: 0.4)),
                ),
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text('Inspired by Krasen (CassidyBOTRR)', style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 4),
                  const Text('Krasen was the first to make a program for remixers and others with AI: Xleth. '
                      'SpartaGen follows that idea.'),
                  const SizedBox(height: 8),
                  Wrap(spacing: 16, children: [
                    TextButton.icon(
                      style: TextButton.styleFrom(padding: EdgeInsets.zero),
                      onPressed: () => openLink(krasenChannel),
                      icon: const Icon(Icons.smart_display_outlined),
                      label: const Text('youtube.com/c/CassidyBOTRR'),
                    ),
                    TextButton.icon(
                      style: TextButton.styleFrom(padding: EdgeInsets.zero),
                      onPressed: () => openLink(krasenGithub),
                      icon: const Icon(Icons.code),
                      label: const Text('github.com/composition-cassidy'),
                    ),
                    TextButton.icon(
                      style: TextButton.styleFrom(padding: EdgeInsets.zero),
                      onPressed: () => openLink(xlethUrl),
                      icon: const Icon(Icons.graphic_eq),
                      label: const Text('Xleth'),
                    ),
                  ]),
                ]),
              ),
              const SizedBox(height: 16),
              Text('Thanks', style: t.titleSmall),
              const SizedBox(height: 4),
              const Text('• The Sparta Remix Wiki and its remixers, for the patterns and the bases.\n'
                  '• FFmpeg, for cutting and encoding.\n'
                  '• mpv / media_kit, for playing video in the app.\n'
                  '• Flutter, for the app itself.'),
              const SizedBox(height: 16),
              Text('Free for everyone', style: t.titleSmall),
              const SizedBox(height: 4),
              const Text(publicDomain),
              const SizedBox(height: 16),
              Text('This is a release candidate: please try everything and report what breaks.',
                  style: TextStyle(color: cs.onSurfaceVariant)),
            ]),
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => showLicensePage(
              context: context,
              applicationName: 'SpartaGen',
              applicationVersion: version,
              applicationLegalese: publicDomain,
              applicationIcon: const Padding(padding: EdgeInsets.all(8), child: AppLogo(size: 48)),
            ),
            child: const Text('Licenses'),
          ),
          FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Close')),
        ],
      );
    },
  );
}
