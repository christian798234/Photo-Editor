"""Convert the official MobileSAM weights to the two ONNX files the app uses.

Provenance script (not needed to use the app). To reproduce:
  1. Copy the `mobile_sam` package and `weights/mobile_sam.pt` from
     https://github.com/ChaoningZhang/MobileSAM into one folder.
  2. pip install torch timm torchvision onnx
  3. Run this script from that folder. It writes mobile_sam_encoder.onnx and
     mobile_sam_decoder.onnx (exact bytes can differ between PyTorch versions;
     the app pins the checksums of the files shipped in backend/models).
"""
import torch, warnings, sys
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")
from mobile_sam import sam_model_registry
from mobile_sam.utils.onnx import SamOnnxModel
sam = sam_model_registry["vit_t"](checkpoint="weights/mobile_sam.pt").eval()

class Enc(torch.nn.Module):
    def __init__(s, m): super().__init__(); s.m = m
    def forward(s, x): return s.m.image_encoder(x)
x = torch.randn(1, 3, 1024, 1024)
torch.onnx.export(Enc(sam), x, "mobile_sam_encoder.onnx", input_names=["image"], output_names=["image_embeddings"],
                  opset_version=17, dynamo=False)
dec = SamOnnxModel(sam, return_single_mask=False)
emb = torch.randn(1, 256, 64, 64)
dummy = {"image_embeddings": emb, "point_coords": torch.randint(0, 1024, (1, 5, 2)).float(),
         "point_labels": torch.randint(0, 4, (1, 5)).float(), "mask_input": torch.randn(1, 1, 256, 256),
         "has_mask_input": torch.tensor([1.0]), "orig_im_size": torch.tensor([1500, 2250]).float()}
torch.onnx.export(dec, tuple(dummy.values()), "mobile_sam_decoder.onnx", input_names=list(dummy),
                  output_names=["masks", "iou_predictions", "low_res_masks"],
                  dynamic_axes={"point_coords": {1: "n"}, "point_labels": {1: "n"}}, opset_version=17, dynamo=False)
print("pixel_mean", sam.pixel_mean.flatten().tolist(), "std", sam.pixel_std.flatten().tolist())
