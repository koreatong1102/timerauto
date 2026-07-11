# Image Path Console Hotfix

- Replaced direct `cv2.imread(...)` calls used for player/spectator portrait files with a unicode-safe reader based on `np.fromfile(...) + cv2.imdecode(...)`.
- This avoids repeated OpenCV `loadsave.cpp: cv::findDecoder imread_... can't open/read file` warnings when the app is run from a Korean/non-ASCII folder path.
- The fix is intentionally narrow: it does not change commentary rules, overlay design, settings UI, or player profile data.
