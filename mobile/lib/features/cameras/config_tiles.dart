import 'package:flutter/material.dart';

import '../../core/theme.dart';

/// Reusable config rows for the camera settings sections.
///
/// The camera page has grown from a handful of toggles to several dozen
/// settings across detection, audio, conversations, incidents and
/// digests. Writing each as a bespoke ListTile made the screen unreadable
/// and every new field a copy-paste. These four cover every shape the
/// camera API actually takes: a bool, a value from a fixed set, a bounded
/// number, and free text.
///
/// All of them are read-only when [enabled] is false, which is how a
/// dependent setting says "turn the parent on first" without vanishing.
/// A control that disappears looks like a missing feature; a greyed one
/// with its reason attached does not.

class ConfigSwitch extends StatelessWidget {
  const ConfigSwitch({
    super.key,
    required this.title,
    required this.value,
    required this.onChanged,
    this.subtitle,
    this.enabled = true,
  });

  final String title;
  final String? subtitle;
  final bool value;
  final ValueChanged<bool> onChanged;
  final bool enabled;

  @override
  Widget build(BuildContext context) => SwitchListTile(
        title: Text(title),
        subtitle: subtitle == null ? null : Text(subtitle!, style: _subStyle),
        value: value,
        activeColor: NurbyColors.accent,
        onChanged: enabled ? onChanged : null,
      );
}

/// One value from a fixed set. Opens a radio sheet rather than a dropdown
/// so the options and their explanations are readable on a phone.
class ConfigChoice<T> extends StatelessWidget {
  const ConfigChoice({
    super.key,
    required this.title,
    required this.value,
    required this.options,
    required this.onChanged,
    this.labels = const {},
    this.hints = const {},
    this.enabled = true,
  });

  final String title;
  final T value;
  final List<T> options;
  final Map<T, String> labels;
  final Map<T, String> hints;
  final ValueChanged<T> onChanged;
  final bool enabled;

  String _label(T v) => labels[v] ?? '$v';

  @override
  Widget build(BuildContext context) => ListTile(
        title: Text(title),
        subtitle: Text(_label(value), style: _subStyle),
        trailing: enabled
            ? const Icon(Icons.chevron_right,
                size: 20, color: NurbyColors.mutedForeground)
            : null,
        enabled: enabled,
        onTap: enabled ? () => _pick(context) : null,
      );

  Future<void> _pick(BuildContext context) async {
    final picked = await showModalBottomSheet<T>(
      context: context,
      backgroundColor: NurbyColors.cardElevated,
      builder: (ctx) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: Text(title,
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            ...options.map(
              (o) => RadioListTile<T>(
                value: o,
                groupValue: value,
                activeColor: NurbyColors.accent,
                title: Text(_label(o)),
                subtitle:
                    hints[o] == null ? null : Text(hints[o]!, style: _subStyle),
                onChanged: (v) => Navigator.pop(ctx, v),
              ),
            ),
            const SizedBox(height: 8),
          ],
        ),
      ),
    );
    if (picked != null && picked != value) onChanged(picked);
  }
}

/// A bounded number. [min] and [max] mirror the server-side validation so
/// a value is rejected here, with an explanation, rather than as a 422
/// from a PATCH that already looked like it worked.
class ConfigNumber extends StatelessWidget {
  const ConfigNumber({
    super.key,
    required this.title,
    required this.value,
    required this.min,
    required this.max,
    required this.onChanged,
    this.suffix = '',
    this.hint,
    this.enabled = true,
  });

  final String title;
  final int value;
  final int min;
  final int max;
  final String suffix;
  final String? hint;
  final ValueChanged<int> onChanged;
  final bool enabled;

  @override
  Widget build(BuildContext context) => ListTile(
        title: Text(title),
        subtitle: Text(
          hint == null ? _display : '$_display · $hint',
          style: _subStyle,
        ),
        trailing: enabled
            ? const Icon(Icons.chevron_right,
                size: 20, color: NurbyColors.mutedForeground)
            : null,
        enabled: enabled,
        onTap: enabled ? () => _edit(context) : null,
      );

  String get _display => suffix.isEmpty ? '$value' : '$value $suffix';

  Future<void> _edit(BuildContext context) async {
    final controller = TextEditingController(text: '$value');
    String? error;
    final result = await showDialog<int>(
      context: context,
      builder: (ctx) => StatefulBuilder(
        builder: (ctx, setLocal) => AlertDialog(
          backgroundColor: NurbyColors.cardElevated,
          title: Text(title),
          content: TextField(
            controller: controller,
            keyboardType: TextInputType.number,
            autofocus: true,
            decoration: InputDecoration(
              suffixText: suffix.isEmpty ? null : suffix,
              helperText: 'Between $min and $max',
              errorText: error,
            ),
          ),
          actions: [
            TextButton(
                onPressed: () => Navigator.pop(ctx),
                child: const Text('Cancel')),
            TextButton(
              onPressed: () {
                final parsed = int.tryParse(controller.text.trim());
                if (parsed == null) {
                  setLocal(() => error = 'Enter a whole number');
                  return;
                }
                if (parsed < min || parsed > max) {
                  setLocal(() => error = 'Must be between $min and $max');
                  return;
                }
                Navigator.pop(ctx, parsed);
              },
              child: const Text('Save'),
            ),
          ],
        ),
      ),
    );
    if (result != null && result != value) onChanged(result);
  }
}

/// Free text, optionally long. An empty result is returned as null so a
/// cleared prompt falls back to the household default rather than pinning
/// the camera to an empty string.
class ConfigText extends StatelessWidget {
  const ConfigText({
    super.key,
    required this.title,
    required this.value,
    required this.onChanged,
    this.placeholder = 'default',
    this.hintText,
    this.maxLines = 4,
    this.maxLength,
    this.enabled = true,
  });

  final String title;
  final String? value;
  final String placeholder;
  final String? hintText;
  final int maxLines;

  /// Mirrors the server's `max_length`. Without it an over-long prompt
  /// looks accepted and comes back 422 from a PATCH the user already
  /// believes succeeded.
  final int? maxLength;
  final ValueChanged<String?> onChanged;
  final bool enabled;

  @override
  Widget build(BuildContext context) => ListTile(
        title: Text(title),
        subtitle: Text(
          (value?.trim().isNotEmpty ?? false) ? value!.trim() : placeholder,
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: _subStyle,
        ),
        trailing: enabled
            ? const Icon(Icons.edit_outlined,
                size: 18, color: NurbyColors.mutedForeground)
            : null,
        enabled: enabled,
        onTap: enabled ? () => _edit(context) : null,
      );

  Future<void> _edit(BuildContext context) async {
    final controller = TextEditingController(text: value ?? '');
    final result = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: NurbyColors.cardElevated,
        title: Text(title),
        content: TextField(
          controller: controller,
          maxLines: maxLines,
          maxLength: maxLength,
          autofocus: true,
          decoration: InputDecoration(hintText: hintText),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, controller.text),
              child: const Text('Save')),
        ],
      ),
    );
    if (result == null) return;
    final trimmed = result.trim();
    onChanged(trimmed.isEmpty ? null : trimmed);
  }
}


/// A list of free-text strings: detection classes, trigger objects,
/// refiner keywords, open-vocabulary prompts.
///
/// Edited in a sheet rather than inline, because these lists are the
/// difference between a camera that watches for the right things and one
/// that fires all day, and they deserve more room than a chip row in a
/// settings list.
class ConfigStringList extends StatelessWidget {
  const ConfigStringList({
    super.key,
    required this.title,
    required this.values,
    required this.onChanged,
    this.hint,
    this.placeholder = 'anything',
    this.inputHint,
    this.enabled = true,
  });

  final String title;
  final List<String> values;

  /// What an empty list means. Usually not "nothing": an empty detection
  /// class list means every class, and saying so is the difference
  /// between a household understanding their camera and not.
  final String placeholder;
  final String? hint;
  final String? inputHint;
  final ValueChanged<List<String>> onChanged;
  final bool enabled;

  @override
  Widget build(BuildContext context) => ListTile(
        title: Text(title),
        subtitle: Text(
          [
            values.isEmpty ? placeholder : values.join(', '),
            if (hint != null) hint!,
          ].join(' · '),
          maxLines: 2,
          overflow: TextOverflow.ellipsis,
          style: _subStyle,
        ),
        trailing: enabled
            ? const Icon(Icons.chevron_right,
                size: 20, color: NurbyColors.mutedForeground)
            : null,
        enabled: enabled,
        onTap: enabled ? () => _edit(context) : null,
      );

  Future<void> _edit(BuildContext context) async {
    final result = await showModalBottomSheet<List<String>>(
      context: context,
      backgroundColor: NurbyColors.cardElevated,
      isScrollControlled: true,
      builder: (ctx) => Padding(
        padding: EdgeInsets.only(
            bottom: MediaQuery.of(ctx).viewInsets.bottom),
        child: _ListEditor(
            title: title, initial: values, inputHint: inputHint),
      ),
    );
    if (result != null) onChanged(result);
  }
}

class _ListEditor extends StatefulWidget {
  const _ListEditor({
    required this.title,
    required this.initial,
    this.inputHint,
  });

  final String title;
  final List<String> initial;
  final String? inputHint;

  @override
  State<_ListEditor> createState() => _ListEditorState();
}

class _ListEditorState extends State<_ListEditor> {
  late final List<String> _values = [...widget.initial];
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _add() {
    final v = _controller.text.trim();
    if (v.isEmpty || _values.contains(v)) return;
    setState(() => _values.add(v));
    _controller.clear();
  }

  @override
  Widget build(BuildContext context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(widget.title,
                  style: const TextStyle(fontWeight: FontWeight.w600)),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: TextField(
                      controller: _controller,
                      autofocus: true,
                      textInputAction: TextInputAction.done,
                      onSubmitted: (_) => _add(),
                      decoration: InputDecoration(
                        hintText: widget.inputHint,
                        isDense: true,
                        border: const OutlineInputBorder(),
                      ),
                    ),
                  ),
                  const SizedBox(width: 8),
                  OutlinedButton(onPressed: _add, child: const Text('Add')),
                ],
              ),
              const SizedBox(height: 12),
              if (_values.isEmpty)
                const Text('Empty.', style: _subStyle)
              else
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final v in _values)
                      Chip(
                        label: Text(v, style: const TextStyle(fontSize: 12)),
                        onDeleted: () =>
                            setState(() => _values.remove(v)),
                      ),
                  ],
                ),
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('Cancel')),
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: () => Navigator.pop(context, _values),
                    child: const Text('Save'),
                  ),
                ],
              ),
            ],
          ),
        ),
      );
}

/// Pick an AI provider by id, or fall back to the household default.
///
/// Null is a real choice here rather than an empty state: a camera with
/// no provider set uses whatever the household picked, and that has to
/// stay selectable or a camera can never be handed back to the default.
class ConfigProvider extends StatelessWidget {
  const ConfigProvider({
    super.key,
    required this.title,
    required this.value,
    required this.providers,
    required this.onChanged,
    this.enabled = true,
  });

  final String title;
  final String? value;

  /// Each entry needs at least `id` and `name`.
  final List<Map<String, dynamic>> providers;
  final ValueChanged<String?> onChanged;
  final bool enabled;

  String get _label {
    if (value == null) return 'Household default';
    for (final p in providers) {
      if (p['id'] == value) return '${p['name']}';
    }
    // Set to a provider this list does not contain: deleted, or not
    // visible to this user. Saying so beats rendering a bare uuid.
    return 'Unknown AI model';
  }

  @override
  Widget build(BuildContext context) => ListTile(
        title: Text(title),
        subtitle: Text(_label, style: _subStyle),
        trailing: enabled
            ? const Icon(Icons.chevron_right,
                size: 20, color: NurbyColors.mutedForeground)
            : null,
        enabled: enabled,
        onTap: enabled ? () => _pick(context) : null,
      );

  Future<void> _pick(BuildContext context) async {
    final picked = await showModalBottomSheet<Object?>(
      context: context,
      backgroundColor: NurbyColors.cardElevated,
      builder: (ctx) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: Text(title,
                  style: const TextStyle(fontWeight: FontWeight.w600)),
            ),
            RadioListTile<String?>(
              value: null,
              groupValue: value,
              activeColor: NurbyColors.accent,
              title: const Text('Household default'),
              onChanged: (_) => Navigator.pop(ctx, _kNullChoice),
            ),
            for (final p in providers)
              RadioListTile<String?>(
                value: p['id'] as String?,
                groupValue: value,
                activeColor: NurbyColors.accent,
                title: Text('${p['name']}'),
                subtitle: p['kind'] == null
                    ? null
                    : Text('${p['kind']}', style: _subStyle),
                onChanged: (v) => Navigator.pop(ctx, v),
              ),
          ],
        ),
      ),
    );
    // Dismissed without choosing returns null, which is also what
    // "household default" means, so that choice carries a sentinel.
    if (picked == null) return;
    final next = picked == _kNullChoice ? null : picked as String;
    if (next != value) onChanged(next);
  }
}

const _kNullChoice = '__default__';

/// The Advanced fold (docs/settings-layers.md).
///
/// Anything with a unit of tokens, seconds or a threshold lives under
/// one of these unless it has a household meaning. Collapsed by default;
/// every field stays reachable, just not at the same weight as
/// "Privacy blur".
class AdvancedFold extends StatelessWidget {
  const AdvancedFold({super.key, required this.children, this.label = 'Advanced'});

  final List<Widget> children;
  final String label;

  @override
  Widget build(BuildContext context) => Theme(
        data: Theme.of(context).copyWith(dividerColor: Colors.transparent),
        child: ExpansionTile(
          tilePadding: const EdgeInsets.symmetric(horizontal: 16),
          title: Text(label,
              style: const TextStyle(fontSize: 13, color: NurbyColors.mutedForeground)),
          iconColor: NurbyColors.mutedForeground,
          collapsedIconColor: NurbyColors.mutedForeground,
          children: children,
        ),
      );
}

const _subStyle =
    TextStyle(color: NurbyColors.mutedForeground, fontSize: 12);
