# Group chat audio and video

Audio notes are recorded in the browser and uploaded as private chat media. Video messages are uploaded as resumable 8 MiB chunks (two at a time), with automatic retries for failed chunks. Videos remain private and are transcoded by the Celery worker into HLS renditions. Playback uses the self-hosted Video.js player with an explicit quality picker and automatic HLS quality selection; it falls back to the original video if transcoding fails.

## Production requirements

- Install FFmpeg, including `ffprobe` and the `libx264` encoder, on the machine running the Celery worker. The worker looks for `ffmpeg` and `ffprobe` on `PATH`.
- Video uploads use 8 MiB chunks, so Nginx no longer needs to accept one 200 MB request. The existing `client_max_body_size 210M;` setting remains compatible; ensure the request limit exceeds 10 MiB for multipart overhead.
- Apply the Django migration and collect static files. Restart the web and Celery services so both load the new model fields and video task.
- Keep enough free space in `PRIVATE_MEDIA_ROOT`: each uploaded original is retained, along with up to five HLS renditions (144p through 720p, capped by the uploaded video resolution).

Video uploads are restricted to group members. The HLS playlists and segments are served through an authenticated view and are not placed under public media storage.
