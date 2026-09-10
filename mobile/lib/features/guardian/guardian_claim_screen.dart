import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import '../../core/theme.dart';

/// Redeem a guardian invite (issue #165).
///
/// Unauthenticated by design: the magic-link token in the invite is the
/// credential. This is the one guardian screen reachable before a
/// session exists, which is why it lives outside the shell.
///
/// The password is chosen and typed by the person claiming the invite.
/// Nothing here generates or suggests one.
class GuardianClaimScreen extends ConsumerStatefulWidget {
  const GuardianClaimScreen({super.key, this.token});

  /// Usually arrives in the link. Editable so someone who copied the
  /// code out of an email by hand is not stuck.
  final String? token;

  @override
  ConsumerState<GuardianClaimScreen> createState() =>
      _GuardianClaimScreenState();
}

class _GuardianClaimScreenState extends ConsumerState<GuardianClaimScreen> {
  late final _token = TextEditingController(text: widget.token ?? '');
  final _password = TextEditingController();
  final _confirm = TextEditingController();
  final _name = TextEditingController();
  bool _busy = false;
  bool _obscure = true;
  String? _error;
  bool _done = false;

  @override
  void dispose() {
    _token.dispose();
    _password.dispose();
    _confirm.dispose();
    _name.dispose();
    super.dispose();
  }

  /// The server requires 8 or more characters. Checking here means a
  /// short password is refused with a reason rather than as a 400 after
  /// the form already looked submitted.
  String? get _passwordProblem {
    if (_password.text.length < 8) return 'Use at least 8 characters.';
    if (_confirm.text != _password.text) return 'The two do not match.';
    return null;
  }

  Future<void> _claim() async {
    final problem = _passwordProblem;
    if (problem != null) {
      setState(() => _error = problem);
      return;
    }
    if (_token.text.trim().isEmpty) {
      setState(() => _error = 'Paste the code from your invite.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(guardianRepoProvider).claim(
            token: _token.text.trim(),
            password: _password.text,
            displayName: _name.text.trim(),
          );
      if (mounted) setState(() => _done = true);
    } catch (e) {
      if (mounted) setState(() => _error = apiErrorMessage(e));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_done) {
      return Scaffold(
        appBar: AppBar(title: const Text('Invite accepted')),
        body: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.check_circle_outline,
                  size: 48, color: NurbyColors.accent),
              const SizedBox(height: 16),
              const Text('Your account is ready.',
                  style: TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 8),
              const Text(
                'Sign in with your email and the password you just set.',
                textAlign: TextAlign.center,
                style: TextStyle(
                    color: NurbyColors.mutedForeground, fontSize: 13),
              ),
              const SizedBox(height: 20),
              FilledButton(
                onPressed: () => Navigator.of(context).pop(),
                child: const Text('Go to sign in'),
              ),
            ],
          ),
        ),
      );
    }

    return Scaffold(
      appBar: AppBar(title: const Text('Accept invite')),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          const Text(
            'Someone has invited you to see a limited view of one person. '
            'Set a password to accept.',
            style: TextStyle(color: NurbyColors.mutedForeground, fontSize: 13),
          ),
          const SizedBox(height: 20),
          TextField(
            controller: _token,
            autocorrect: false,
            maxLines: 2,
            decoration: const InputDecoration(
              labelText: 'Invite code',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _name,
            decoration: const InputDecoration(
              labelText: 'Your name (optional)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _password,
            obscureText: _obscure,
            autocorrect: false,
            onChanged: (_) => setState(() {}),
            decoration: InputDecoration(
              labelText: 'Choose a password',
              helperText: 'At least 8 characters',
              border: const OutlineInputBorder(),
              suffixIcon: IconButton(
                icon: Icon(
                    _obscure ? Icons.visibility_off : Icons.visibility,
                    size: 18),
                onPressed: () => setState(() => _obscure = !_obscure),
              ),
            ),
          ),
          const SizedBox(height: 12),
          TextField(
            controller: _confirm,
            obscureText: _obscure,
            autocorrect: false,
            onChanged: (_) => setState(() {}),
            decoration: const InputDecoration(
              labelText: 'Type it again',
              border: OutlineInputBorder(),
            ),
          ),
          if (_error != null) ...[
            const SizedBox(height: 12),
            Text(_error!,
                style: const TextStyle(color: NurbyColors.danger, fontSize: 13)),
          ],
          const SizedBox(height: 20),
          FilledButton(
            onPressed: _busy ? null : _claim,
            child: _busy
                ? const SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2))
                : const Text('Accept invite'),
          ),
        ],
      ),
    );
  }
}
