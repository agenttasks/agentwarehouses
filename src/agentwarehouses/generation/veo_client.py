"""Veo 3.1 video generation client using the google-genai SDK.

Wraps the Google GenAI Python SDK for programmatic video generation
with Veo 3.1 models, including polling for async generation results.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from google import genai
from google.genai import types

from agentwarehouses.log import get_logger
from agentwarehouses.models.video import (
    GenerationConfig,
    GenerationTask,
    VideoAsset,
    VideoMetadata,
    VideoResolution,
    VideoStatus,
)

logger = get_logger(__name__)

# Resolution to pixel dimensions for Veo 3.1
_RESOLUTION_MAP: dict[VideoResolution, tuple[int, int]] = {
    VideoResolution.SD_480P: (480, 854),
    VideoResolution.HD_720P: (720, 1280),
    VideoResolution.HD_1080P: (1080, 1920),
    VideoResolution.UHD_4K: (2160, 3840),
}


class VeoClient:
    """Client for Veo 3.1 video generation via google-genai SDK."""

    def __init__(self, api_key: str | None = None) -> None:
        self._client = genai.Client(api_key=api_key or os.environ.get("GOOGLE_API_KEY"))

    def submit_generation(
        self,
        prompt: str,
        config: GenerationConfig | None = None,
        title: str = "Untitled",
        tags: list[str] | None = None,
    ) -> tuple[object, GenerationTask]:
        """Submit a video generation request to Veo 3.1.

        Returns (operation, GenerationTask). Pass the operation to
        poll_generation() to wait for completion.
        """
        config = config or GenerationConfig()
        task_id = str(uuid.uuid4())

        logger.info("Submitting Veo 3.1 generation task %s (model=%s)", task_id, config.model.value)

        operation = self._client.models.generate_videos(
            model=config.model.value,
            prompt=prompt,
            config=types.GenerateVideosConfig(
                person_generation=config.person_generation,
                aspect_ratio=config.aspect_ratio,
                number_of_videos=1,
            ),
        )

        task = GenerationTask(
            id=task_id,
            prompt=prompt,
            config=config,
            status=VideoStatus.GENERATING,
            video_asset=VideoAsset(
                id=str(uuid.uuid4()),
                status=VideoStatus.GENERATING,
                metadata=VideoMetadata(
                    title=title,
                    resolution=config.resolution,
                    duration_seconds=config.duration_seconds,
                    has_audio=True,
                    tags=tags or [],
                ),
                generation_task_id=task_id,
            ),
            created_at=datetime.utcnow(),
        )

        return operation, task

    def poll_generation(
        self,
        operation: object,
        task: GenerationTask,
        output_dir: str = "output/videos",
        poll_interval: float = 5.0,
        max_wait: float = 600.0,
    ) -> GenerationTask:
        """Poll a Veo 3.1 generation operation until completion.

        Saves the resulting video to output_dir and updates the task status.
        """
        elapsed = 0.0

        while not operation.done:
            if elapsed >= max_wait:
                logger.warning("Generation task %s timed out after %.0fs", task.id, max_wait)
                task.status = VideoStatus.FAILED
                task.error = f"Generation timed out after {max_wait}s"
                return task

            time.sleep(poll_interval)
            elapsed += poll_interval
            logger.info("Polling task %s (%.0fs elapsed)", task.id, elapsed)
            operation = self._client.operations.get(operation)

        # Extract generated video
        result = operation.result
        if not result or not result.generated_videos:
            task.status = VideoStatus.FAILED
            task.error = "No videos returned from Veo 3.1"
            return task

        video = result.generated_videos[0]

        # Save to disk
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        file_name = f"{task.id}.mp4"
        file_path = out_path / file_name

        video_data = self._client.files.download(file=video.video)
        file_path.write_bytes(video_data)

        logger.info("Video saved to %s", file_path)

        task.status = VideoStatus.READY
        if task.video_asset:
            task.video_asset.status = VideoStatus.READY
            task.video_asset.url = str(file_path)
            task.video_asset.updated_at = datetime.utcnow()

        return task

    def generate_and_wait(
        self,
        prompt: str,
        config: GenerationConfig | None = None,
        title: str = "Untitled",
        tags: list[str] | None = None,
        output_dir: str = "output/videos",
    ) -> GenerationTask:
        """Submit generation and block until the video is ready.

        Combines submit_generation + poll_generation for simple use cases.
        """
        config = config or GenerationConfig()
        task_id = str(uuid.uuid4())

        logger.info("Starting Veo 3.1 generation (blocking) task %s", task_id)

        operation = self._client.models.generate_videos(
            model=config.model.value,
            prompt=prompt,
            config=types.GenerateVideosConfig(
                person_generation=config.person_generation,
                aspect_ratio=config.aspect_ratio,
                number_of_videos=1,
            ),
        )

        task = GenerationTask(
            id=task_id,
            prompt=prompt,
            config=config,
            status=VideoStatus.GENERATING,
            video_asset=VideoAsset(
                id=str(uuid.uuid4()),
                status=VideoStatus.GENERATING,
                metadata=VideoMetadata(
                    title=title,
                    resolution=config.resolution,
                    duration_seconds=config.duration_seconds,
                    has_audio=True,
                    tags=tags or [],
                ),
                generation_task_id=task_id,
            ),
        )

        return self.poll_generation(operation, task, output_dir=output_dir)
