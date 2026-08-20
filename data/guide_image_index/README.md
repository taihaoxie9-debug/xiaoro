# Guide Image Index Artifacts

This directory contains reproducible, non-canonical image retrieval
artifacts. Canonical product and source-image facts remain under
`data/canonical/` and are read-only inputs.

Build the locked Slice 2.0 index with:

```bash
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /private/tmp/xiaoro-guide-image-venv/bin/python \
  -m tools.guide_gates.build_guide_image_index \
  --repo-root "$PWD" \
  --weight-path /absolute/path/to/open_clip_model.safetensors \
  --output-dir "$PWD/data/guide_image_index/openclip_vit_b32_laion2b_s34b_b79k_v1" \
  --repeat-output-dir /private/tmp/xiaoro-slice20-task11-repeat-index \
  --report-path "$PWD/docs/audits/slice2.0/task11_build_report.json" \
  --device mps \
  --batch-size 16
```

The command refuses existing output directories. It never downloads model
weights and does not store the approved weight or virtual environment here.
