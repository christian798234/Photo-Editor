# Bird detection models (optional feature)

These files power the optional bird-aware processing. They run locally with
ONNX Runtime on the CPU. Photos are never uploaded anywhere.

| File | What it is | Licence | SHA-256 |
|---|---|---|---|
| `yolox_s.onnx` | YOLOX-S object detector (COCO classes; only "bird" is used). Unmodified official ONNX file from the [YOLOX 0.1.1rc0 release](https://github.com/Megvii-BaseDetection/YOLOX/releases/tag/0.1.1rc0). | Apache-2.0 (`LICENSE-YOLOX.txt`) | `c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063` |
| `mobile_sam_encoder.onnx` | MobileSAM image encoder | Apache-2.0 (`LICENSE-MobileSAM.txt`) | `2c8c3bc527b63f798e52b921980259f9ffffe3fe78cba97967b019628a5ca3c7` |
| `mobile_sam_decoder.onnx` | MobileSAM prompt/mask decoder | Apache-2.0 | `8f72ca4fb1b501bd030c19090f39d547987b609f79c1e9fc66f13b06a71d431f` |

The two MobileSAM files were converted from the official weights
`weights/mobile_sam.pt` in <https://github.com/ChaoningZhang/MobileSAM>
(SHA-256 `6dbb90523a35330fedd7f1d3dfc66f995213d81b29a5ca8108dbcdd4e37d6c2f`)
with `scripts/export_mobilesam_onnx.py` (PyTorch 2.15, ONNX opset 17). The
weights themselves were not changed.

The app checks these checksums before using the models.
