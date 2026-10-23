# Recorded walkthrough video

`dist/skillguard-demo-video.mp4` is the finished local 2:19 video. It shows actual browser-page captures of the explicitly approved public walkthrough, with local system-voice narration from `narration.txt`. It is not footage of a fresh native run or the protected Codex application. The persistent footer says recorded evidence replay, fictional staged attack and edited timing. Public upload was declined by the user.

The browser capture contains 266 frames at an approximate two-per-second acquisition cadence, edited to the narration. Navigation/tool pauses were removed and scene durations adjusted. The footage is not a latency measurement. The encoded file has H.264 video at 1440×798, AAC audio, 24 output frames/second, and duration 139.25 seconds.

| Time | Actual captured page |
| --- | --- |
| 0:00–0:25 | Public walkthrough introduction |
| 0:25–0:46 | Blocked staged skill update and native comparison |
| 0:46–1:05 | Four generated annotation/control tabs and preserved receipt result |
| 1:05–1:19 | Archived native agent terminal commands |
| 1:19–1:56 | Declared sandbox boundary and retained model hold explanation |
| 1:56–2:05 | Recorded human exception, installation and rollback |
| 2:05–2:12.5 | Evidence limits and retained incomplete trial |
| 2:12.5–2:19.25 | Closing introduction view |

Verification: decoded the entire MP4, checked both streams and duration, inspected representative encoded frames, and measured non-silent audio without clipping. Source frames and the edit manifest remain locally under `dist/video-frames`. No extra model calls were used for recording. No YouTube URL exists and no Devpost submission has been made.

For a future live-product recording, use the real local app at http://127.0.0.1:8768/ and identify which actions execute now versus display archived evidence. The public URL is a separate replay. Never call the replay a live attack, general protection, a blind benchmark, a model-approved pass or a cloud sandbox deployment.
