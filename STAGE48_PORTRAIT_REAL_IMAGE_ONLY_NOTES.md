# STAGE48 Portrait Real-Image-Only FX

## What changed
- Disabled the extra `.portraitFxLayer` visual layer completely.
- Kept the effect on the real portrait image only.
- Restored portrait shake/impact movement using the real `.portrait` element.
- Kept clipping/rounded rectangle protection so the portrait flash does not spill outside the image.

## Why
Stage46/47 made a separate local FX layer visible over the portrait. It prevented overflow after Stage47, but visually it could look like a second artificial light effect. Stage48 removes that duplicate layer and uses only image brightness/drop-shadow + small impact motion on the portrait itself.

## Files changed
- `browser_overlay.py`
