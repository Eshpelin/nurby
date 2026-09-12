import 'package:flutter_test/flutter_test.dart';
import 'package:nurby_mobile/features/cameras/detection_models_editor.dart';

void main() {
  group('modelFilename', () {
    test('composes the ultralytics filenames the backend loads', () {
      expect(modelFilename('YOLOv8', 'n'), 'yolov8n.pt');
      expect(modelFilename('YOLO11', 'm'), 'yolo11m.pt');
      expect(modelFilename('YOLO-World', 's'), 'yolov8s-worldv2.pt');
      expect(modelFilename('Open Images V7', 'l'), 'yolov8l-oiv7.pt');
      expect(modelFilename('YOLO11 Segmentation', 'n'), 'yolo11n-seg.pt');
    });

    test('RT-DETR only ships in l and x', () {
      expect(modelFilename('RT-DETR', 'x'), 'rtdetr-x.pt');
      expect(modelFilename('RT-DETR', 'n'), 'rtdetr-l.pt');
    });
  });

  group('modelLabel', () {
    test('round-trips every catalogue filename to a readable name', () {
      expect(modelLabel('yolov8n.pt'), 'YOLOv8 N');
      expect(modelLabel('yolo11x.pt'), 'YOLO11 X');
      expect(modelLabel('yolov8s-worldv2.pt'), 'YOLOv8 World S');
      expect(modelLabel('yolov8m-oiv7.pt'), 'YOLOv8 Open Images M');
      expect(modelLabel('yolo11n-seg.pt'), 'YOLO11 Seg N');
      expect(modelLabel('rtdetr-l.pt'), 'RT-DETR L');
    });

    test('a custom filename typed on web is shown as-is, not misread', () {
      // Someone entered their own model on web. Mangling it into a
      // catalogue name would claim it is something it is not.
      expect(modelLabel('my-finetuned-v3.pt'), 'my-finetuned-v3.pt');
    });
  });
}
