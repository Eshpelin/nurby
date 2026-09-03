import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/theme.dart';

/// Per-camera detection models (issue #160, deferred part).
///
/// A camera runs one or more detector models and merges their output.
/// Each entry is `{model, confidence, enabled, label_filter}`, read by
/// `services/perception/detector.py`. An empty list means the default
/// model alone, so removing the last entry is not "no detection", it is
/// "back to the default", and the editor says so.

/// The catalogue web offers, as family plus size. Any filename the
/// backend can load is valid; these are the ones with known trade-offs.
const kModelFamilies = [
  ('yolov8', 'YOLOv8', 'COCO 80 classes. The default.'),
  ('yolo11', 'YOLO11', 'COCO 80 classes, newer.'),
  ('yolov8', 'YOLO-World', 'Open vocabulary, driven by the prompts above.'),
  ('yolov8-oiv7', 'Open Images V7', '600+ classes.'),
  ('yolo11-seg', 'YOLO11 Segmentation', 'Masks, for tighter privacy blur.'),
  ('rtdetr', 'RT-DETR', 'Transformer detector.'),
];

const kModelSizes = ['n', 's', 'm', 'l', 'x'];

/// The filename for a family and size. Pure. YOLO-World has its own
/// suffix convention and RT-DETR only ships in two sizes.
String modelFilename(String familyLabel, String size) {
  switch (familyLabel) {
    case 'YOLO-World':
      return 'yolov8$size-worldv2.pt';
    case 'Open Images V7':
      return 'yolov8$size-oiv7.pt';
    case 'YOLO11 Segmentation':
      return 'yolo11$size-seg.pt';
    case 'RT-DETR':
      return 'rtdetr-${size == 'x' ? 'x' : 'l'}.pt';
    case 'YOLO11':
      return 'yolo11$size.pt';
    default:
      return 'yolov8$size.pt';
  }
}

/// A human label for a stored filename. Pure. Unknown files are shown
/// as-is: someone typed a custom model on web and it should not read as
/// something else here.
String modelLabel(String filename) {
  final m = RegExp(r'^(yolov8|yolo11|rtdetr)(?:-)?([nsmlx])?(-worldv2|-world|-oiv7|-seg)?\.pt$')
      .firstMatch(filename);
  if (m == null) return filename;
  final size = m.group(2)?.toUpperCase();
  final variant = m.group(3) ?? '';
  final base = switch (m.group(1)) {
    'yolo11' => 'YOLO11',
    'rtdetr' => 'RT-DETR',
    _ => 'YOLOv8',
  };
  final suffix = switch (variant) {
    '-worldv2' || '-world' => ' World',
    '-oiv7' => ' Open Images',
    '-seg' => ' Seg',
    _ => '',
  };
  return '$base$suffix${size == null ? '' : ' $size'}';
}

class DetectionModelsEditor extends ConsumerStatefulWidget {
  const DetectionModelsEditor({
    super.key,
    required this.initial,
    required this.onSave,
  });

  final List<Map<String, dynamic>> initial;
  final Future<void> Function(List<Map<String, dynamic>>) onSave;

  @override
  ConsumerState<DetectionModelsEditor> createState() =>
      _DetectionModelsEditorState();
}

class _DetectionModelsEditorState extends ConsumerState<DetectionModelsEditor> {
  late final List<Map<String, dynamic>> _models = [
    for (final m in widget.initial) {...m},
  ];
  bool _busy = false;

  void _add() {
    setState(() => _models.add({
          'model': 'yolov8n.pt',
          'confidence': 0.5,
          'enabled': true,
          'label_filter': null,
        }));
  }

  Future<void> _save() async {
    setState(() => _busy = true);
    try {
      await widget.onSave(_models);
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(apiErrorMessage(e))));
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Padding(
        padding: EdgeInsets.only(
          left: 16,
          right: 16,
          top: 16,
          bottom: MediaQuery.of(context).viewInsets.bottom + 16,
        ),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text('Detection models',
                  style: TextStyle(fontSize: 17, fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              Text(
                _models.isEmpty
                    ? 'None configured, so the default (YOLOv8 N) runs alone.'
                    : '${_models.length} ${_models.length == 1 ? 'model' : 'models'}. '
                        'Results are merged the way the Detection tuning '
                        'section says.',
                style: _sub,
              ),
              const SizedBox(height: 12),
              for (var i = 0; i < _models.length; i++)
                _ModelRow(
                  config: _models[i],
                  onChanged: (next) => setState(() => _models[i] = next),
                  onRemove: () => setState(() => _models.removeAt(i)),
                ),
              OutlinedButton.icon(
                onPressed: _add,
                icon: const Icon(Icons.add, size: 16),
                label: const Text('Add a model'),
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
                      onPressed: _busy ? null : _save,
                      child: const Text('Save')),
                ],
              ),
            ],
          ),
        ),
      );
}

class _ModelRow extends StatelessWidget {
  const _ModelRow({
    required this.config,
    required this.onChanged,
    required this.onRemove,
  });

  final Map<String, dynamic> config;
  final ValueChanged<Map<String, dynamic>> onChanged;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final file = config['model'] as String? ?? 'yolov8n.pt';
    final conf = (config['confidence'] as num?)?.toDouble() ?? 0.5;
    final enabled = config['enabled'] as bool? ?? true;
    final filter = (config['label_filter'] as List?)?.map((e) => '$e').toList();

    return Card(
      margin: const EdgeInsets.only(bottom: 8),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 4, 4, 8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: InkWell(
                    onTap: () => _pickModel(context),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(modelLabel(file),
                              style: const TextStyle(
                                  fontWeight: FontWeight.w600, fontSize: 14)),
                          Text(file, style: _mono),
                        ],
                      ),
                    ),
                  ),
                ),
                Switch(
                  value: enabled,
                  activeColor: NurbyColors.accent,
                  onChanged: (v) => onChanged({...config, 'enabled': v}),
                ),
                IconButton(
                  icon: const Icon(Icons.close, size: 18),
                  onPressed: onRemove,
                ),
              ],
            ),
            Row(
              children: [
                const Text('Confidence', style: _sub),
                Expanded(
                  child: Slider(
                    value: conf.clamp(0.05, 0.95),
                    min: 0.05,
                    max: 0.95,
                    divisions: 18,
                    activeColor: NurbyColors.accent,
                    label: conf.toStringAsFixed(2),
                    onChanged: enabled
                        ? (v) => onChanged({
                              ...config,
                              'confidence': double.parse(v.toStringAsFixed(2)),
                            })
                        : null,
                  ),
                ),
                SizedBox(
                    width: 36,
                    child: Text(conf.toStringAsFixed(2), style: _mono)),
              ],
            ),
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Text(
                filter == null || filter.isEmpty
                    ? 'Keeps every label this model finds.'
                    : 'Keeps only: ${filter.join(', ')}',
                style: _sub,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Future<void> _pickModel(BuildContext context) async {
    final picked = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: NurbyColors.cardElevated,
      isScrollControlled: true,
      builder: (ctx) => SafeArea(
        child: ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.only(bottom: 12),
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 16, 16, 8),
              child: Text('Which model',
                  style: TextStyle(fontWeight: FontWeight.w600)),
            ),
            for (final (_, label, hint) in kModelFamilies)
              ExpansionTile(
                title: Text(label, style: const TextStyle(fontSize: 14)),
                subtitle: Text(hint, style: _sub),
                childrenPadding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
                children: [
                  Wrap(
                    spacing: 6,
                    children: [
                      for (final size in (label == 'RT-DETR' ? ['l', 'x'] : kModelSizes))
                        ActionChip(
                          label: Text(size.toUpperCase()),
                          onPressed: () =>
                              Navigator.pop(ctx, modelFilename(label, size)),
                        ),
                    ],
                  ),
                  const Padding(
                    padding: EdgeInsets.only(top: 6),
                    child: Text('N is fastest, X is most accurate.', style: _sub),
                  ),
                ],
              ),
          ],
        ),
      ),
    );
    if (picked != null) onChanged({...config, 'model': picked});
  }
}

const _sub = TextStyle(color: NurbyColors.mutedForeground, fontSize: 12);
const _mono = TextStyle(fontFamily: 'Menlo', fontSize: 11, color: NurbyColors.mutedForeground);
