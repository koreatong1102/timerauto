
STAGE40B portrait clone sizing hotfix

- Fixed portraitFlashImg clone using old 74x74 size while the real portrait is 122x122.
- Fixed portraitFlashImg z-index being lower than the real portrait, which made the effect appear behind the portrait.
- portraitFlashImage now copies the computed top/left/right/width/height/object-fit/z-index from the real portrait image before playing the flash animation.
