import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

/// Outbound webhook subscriptions (issue #169).
///
/// Kept deliberately small on mobile: list, enable, delete, and a create
/// form with name, URL and secret. Scoping a subscription to specific
/// rules or cameras is a laptop task and is left to web.
final webhooksProvider = FutureProvider<List<Map<String, dynamic>>>(
    (ref) async => ((await ref
                .watch(apiClientProvider)
                .getJson('/api/webhook-subscriptions')) as List)
            .whereType<Map>()
            .map((w) => w.cast<String, dynamic>())
            .toList());

class WebhooksSection extends ConsumerWidget {
  const WebhooksSection({super.key, required this.isAdmin});

  final bool isAdmin;

  Future<void> _toggle(WidgetRef ref, BuildContext context,
      Map<String, dynamic> w, bool on) async {
    try {
      await ref
          .read(apiClientProvider)
          .patchJson('/api/webhook-subscriptions/${w['id']}',
              body: {'active': on});
      ref.invalidate(webhooksProvider);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  Future<void> _delete(WidgetRef ref, BuildContext context,
      Map<String, dynamic> w) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: const Text('Delete webhook?'),
        content: Text('"${w['name']}" will stop receiving events.'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Cancel')),
          TextButton(
            onPressed: () => Navigator.pop(ctx, true),
            child: const Text('Delete',
                style: TextStyle(color: NurbyColors.danger)),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref
          .read(apiClientProvider)
          .delete('/api/webhook-subscriptions/${w['id']}');
      ref.invalidate(webhooksProvider);
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final async = ref.watch(webhooksProvider);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Padding(
          padding: const EdgeInsets.only(top: 18, bottom: 8, left: 4),
          child: Row(
            children: [
              const Expanded(
                child: Text('WEBHOOKS',
                    style: TextStyle(
                        fontFamily: 'Menlo',
                        fontSize: 10,
                        letterSpacing: 1.4,
                        color: NurbyColors.accent,
                        fontWeight: FontWeight.w600)),
              ),
              if (isAdmin)
                TextButton.icon(
                  icon: const Icon(Icons.add, size: 16),
                  label: const Text('Add'),
                  onPressed: () => showModalBottomSheet<void>(
                    context: context,
                    isScrollControlled: true,
                    backgroundColor: NurbyColors.cardElevated,
                    builder: (_) => const _WebhookForm(),
                  ),
                ),
            ],
          ),
        ),
        Card(
          child: async.when(
            loading: () => const ListTile(title: LinearProgressIndicator()),
            error: (e, _) => ListTile(
                title: Text(apiErrorMessage(e), style: _sub)),
            data: (rows) => rows.isEmpty
                ? const ListTile(
                    title: Text('No webhooks', style: TextStyle(fontSize: 13)),
                    subtitle: Text(
                      'Send every event to a URL of your own, signed with '
                      'a secret.',
                      style: _sub,
                    ),
                  )
                : Column(children: [
                    for (final w in rows)
                      ListTile(
                        dense: true,
                        title: Text('${w['name']}',
                            style: const TextStyle(fontSize: 13)),
                        subtitle: Text('${w['url']}',
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: _sub),
                        trailing: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            Switch(
                              value: w['active'] == true,
                              activeColor: NurbyColors.accent,
                              onChanged: isAdmin
                                  ? (on) => _toggle(ref, context, w, on)
                                  : null,
                            ),
                            if (isAdmin)
                              IconButton(
                                icon: const Icon(Icons.delete_outline,
                                    size: 18),
                                onPressed: () => _delete(ref, context, w),
                              ),
                          ],
                        ),
                      ),
                  ]),
          ),
        ),
      ],
    );
  }
}

class _WebhookForm extends ConsumerStatefulWidget {
  const _WebhookForm();

  @override
  ConsumerState<_WebhookForm> createState() => _WebhookFormState();
}

class _WebhookFormState extends ConsumerState<_WebhookForm> {
  final _name = TextEditingController();
  final _url = TextEditingController();
  final _secret = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _url.dispose();
    _secret.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    final url = _url.text.trim();
    final uri = Uri.tryParse(url);
    // The server hardens against private-network targets separately;
    // this only catches something that is not a URL at all.
    if (uri == null || !(uri.isScheme('http') || uri.isScheme('https'))) {
      setState(() => _error = 'That is not an http or https URL.');
      return;
    }
    if (_name.text.trim().isEmpty) {
      setState(() => _error = 'Give it a name.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(apiClientProvider).postJson('/api/webhook-subscriptions',
          body: {
            'name': _name.text.trim(),
            'url': url,
            if (_secret.text.isNotEmpty) 'secret': _secret.text,
            'active': true,
          });
      ref.invalidate(webhooksProvider);
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(
          left: 20,
          right: 20,
          top: 20,
          bottom: MediaQuery.of(context).viewInsets.bottom + 24,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('New webhook',
                style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
            const SizedBox(height: 16),
            TextField(
              controller: _name,
              decoration: const InputDecoration(
                  labelText: 'Name', border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _url,
              autocorrect: false,
              keyboardType: TextInputType.url,
              decoration: const InputDecoration(
                  labelText: 'URL',
                  hintText: 'https://example.com/nurby',
                  border: OutlineInputBorder()),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _secret,
              autocorrect: false,
              obscureText: true,
              decoration: const InputDecoration(
                  labelText: 'Signing secret (optional)',
                  helperText: 'Sent as an HMAC so the receiver can verify us.',
                  border: OutlineInputBorder()),
            ),
            if (_error != null) ...[
              const SizedBox(height: 10),
              Text(_error!,
                  style: const TextStyle(
                      color: NurbyColors.danger, fontSize: 13)),
            ],
            const SizedBox(height: 16),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('Cancel')),
                const SizedBox(width: 8),
                FilledButton(
                    onPressed: _busy ? null : _save,
                    child: const Text('Create')),
              ],
            ),
          ],
        ),
      );
}

const _sub = TextStyle(color: NurbyColors.mutedForeground, fontSize: 12);
