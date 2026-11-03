# Group chat audio and video

Audio notes are recorded in the browser and uploaded as private chat media. Videos are kept privately and transcoded by the Celery worker into HLS renditions; the player uses automatic HLS quality selection and falls back to the original video if transcoding fails.

## Production requirements

- Install FFmpeg, including `ffprobe` and the `libx264` encoder, on the machine running the Celery worker. The worker looks for `ffmpeg` and `ffprobe` on `PATH`.
- Increase the site's Nginx upload limit to at least `210M` (`client_max_body_size 210M;`) to accept the 200 MB video limit.
- Apply the Django migration and collect static files. Restart the web and Celery services so both load the new model fields and video task.
- Keep enough free space in `PRIVATE_MEDIA_ROOT`: each uploaded original is retained, along with up to four HLS renditions.

Video uploads are restricted to group members. The HLS playlists and segments are served through an authenticated view and are not placed under public media storage.
