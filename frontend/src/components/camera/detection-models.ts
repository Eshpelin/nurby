/** Detection-model catalog, shared by the camera page and the model
 * picker. */

export interface DetectionModelOption {
  value: string;
  label: string;
  hint: string;
  family: "yolov8" | "yolo11" | "yolo-world" | "rtdetr" | "oiv7" | "yolo11-seg";
}

export const DETECTION_MODEL_CATALOG: DetectionModelOption[] = [
  { value: "yolov8n.pt", label: "YOLOv8 Nano",   hint: "Fastest. 80 COCO classes. ~6ms on CPU.",       family: "yolov8" },
  { value: "yolov8s.pt", label: "YOLOv8 Small",  hint: "Balanced speed and accuracy. 80 COCO classes.", family: "yolov8" },
  { value: "yolov8m.pt", label: "YOLOv8 Medium", hint: "Better accuracy, slower. 80 COCO classes.",     family: "yolov8" },
  { value: "yolov8l.pt", label: "YOLOv8 Large",  hint: "High accuracy. GPU recommended.",               family: "yolov8" },
  { value: "yolov8x.pt", label: "YOLOv8 XLarge", hint: "Top YOLOv8 accuracy. GPU strongly advised.",    family: "yolov8" },
  { value: "yolo11n.pt", label: "YOLO11 Nano",   hint: "Newer gen. Slightly better than v8n.",          family: "yolo11" },
  { value: "yolo11s.pt", label: "YOLO11 Small",  hint: "Newer gen. Drop-in upgrade for v8s.",           family: "yolo11" },
  { value: "yolo11m.pt", label: "YOLO11 Medium", hint: "Newer gen medium. Good accuracy tradeoff.",     family: "yolo11" },
  { value: "yolo11l.pt", label: "YOLO11 Large",  hint: "Newer gen large. GPU recommended.",             family: "yolo11" },
  { value: "yolo11x.pt", label: "YOLO11 XLarge", hint: "Top-tier detection, GPU needed for realtime.",  family: "yolo11" },
  { value: "yolov8n-oiv7.pt", label: "YOLOv8n Open Images", hint: "600+ classes (furniture, tools, food, animals).", family: "oiv7" },
  { value: "yolov8s-oiv7.pt", label: "YOLOv8s Open Images", hint: "600+ classes, better accuracy.",     family: "oiv7" },
  { value: "yolov8m-oiv7.pt", label: "YOLOv8m Open Images", hint: "600+ classes, medium accuracy.",     family: "oiv7" },
  { value: "yolov8x-oiv7.pt", label: "YOLOv8x Open Images", hint: "600+ classes, TOP OIV7 accuracy. GPU recommended.", family: "oiv7" },
  { value: "yolov8s-world.pt", label: "YOLO-World v1 Small", hint: "Open-vocabulary v1. Older, kept for back-compat.", family: "yolo-world" },
  { value: "yolov8m-world.pt", label: "YOLO-World v1 Medium", hint: "Open-vocabulary v1, better recall.", family: "yolo-world" },
  { value: "yolov8s-worldv2.pt", label: "YOLO-World v2 Small", hint: "Open-vocab v2. Faster, decent accuracy.", family: "yolo-world" },
  { value: "yolov8m-worldv2.pt", label: "YOLO-World v2 Medium", hint: "Open-vocab v2 balanced.", family: "yolo-world" },
  { value: "yolov8l-worldv2.pt", label: "YOLO-World v2 Large", hint: "Open-vocab v2 large.", family: "yolo-world" },
  { value: "yolov8x-worldv2.pt", label: "YOLO-World v2 XLarge ★", hint: "RECOMMENDED. Top open-vocab accuracy across LVIS. Prompt any class by English name. GPU recommended.", family: "yolo-world" },
  { value: "yolo11n-seg.pt", label: "YOLO11n Seg", hint: "Segmentation masks. Tighter privacy blur shapes.", family: "yolo11-seg" },
  { value: "yolo11s-seg.pt", label: "YOLO11s Seg", hint: "Segmentation, balanced. Recommended for mask-based privacy.", family: "yolo11-seg" },
  { value: "yolo11m-seg.pt", label: "YOLO11m Seg", hint: "Segmentation, better accuracy.",                family: "yolo11-seg" },
  { value: "yolo11l-seg.pt", label: "YOLO11l Seg", hint: "Segmentation, large. GPU recommended.",         family: "yolo11-seg" },
  { value: "yolo11x-seg.pt", label: "YOLO11x Seg ★", hint: "Top segmentation accuracy. GPU required.",     family: "yolo11-seg" },
  { value: "rtdetr-l.pt", label: "RT-DETR Large",  hint: "Transformer-based. Strong on small / crowded objects.", family: "rtdetr" },
  { value: "rtdetr-x.pt", label: "RT-DETR XLarge", hint: "Top RT-DETR. GPU required for realtime.",      family: "rtdetr" },
];
