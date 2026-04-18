---
name: tiktok-video-pipeline
description: Research viral trends, generate short-form AI videos via ComfyUI, and publish them to TikTok through a coordinated three-agent pipeline.
metadata: {"openclaw":{"skillKey":"tiktok-video-pipeline"}}
---

# TikTok Video Pipeline

Use this skill when the user wants to research viral video trends, generate AI-powered short-form videos, or publish content to TikTok.

## Trigger

```json
{
  "activation": {
    "anyPhrases": [
      "find viral trends",
      "viral video",
      "generate video",
      "create video",
      "make a video",
      "upload to tiktok",
      "post to tiktok",
      "tiktok video",
      "video pipeline",
      "trending content",
      "content pipeline"
    ]
  },
  "movement": {
    "target": "github",
    "skipIfAlreadyThere": true
  }
}
```

When this skill is activated, the agent should move to the server room before handling the request — video generation and publishing are production workloads.

## Three-Agent Pipeline

This skill coordinates work across three specialized agents:

### 1. Scout (Trend Research)
- Monitors TikTok trending feeds and FYP engagement patterns.
- Identifies high-potential video formats, hashtag clusters, and optimal posting windows.
- Produces a **trend brief** with format recommendation, hashtag strategy, and audience targeting.

### 2. Forge (Content Generation)
- Receives the trend brief from Scout.
- Generates key frames using ComfyUI (txt2img, 384×384, euler_ancestral).
- Assembles frames into a 5–15 second video using FFmpeg with Ken Burns effects and crossfade transitions.
- Optionally overlays background audio from the session music library.
- Produces a final MP4 ready for upload.

### 3. Nova (TikTok Publisher)
- Receives the rendered video from Forge.
- Uploads to TikTok via the Content Posting API v2 (`/v2/post/publish/video/init/`).
- Monitors upload processing status and publishes engagement metrics.
- Tracks performance across published videos for optimization feedback.

## Storage Location

Pipeline state is stored in `.agents/tiktok-pipeline/` in the workspace root.

- `pipeline-state.json` — Current pipeline status, active jobs, and queue.
- `trend-reports/` — Scout's trend analysis reports (one per research cycle).
- `generated-videos/` — Forge's rendered video outputs.
- `upload-receipts/` — Nova's TikTok upload confirmations and metrics snapshots.

Create the directory structure if it does not exist.

## Pipeline State Schema

```json
{
  "version": 1,
  "updatedAt": "2026-04-15T00:00:00.000Z",
  "activeJob": {
    "id": "pipeline-001",
    "status": "generating",
    "trendBrief": {
      "format": "Satisfying Process Loop",
      "hashtags": ["#satisfying", "#aiart", "#fyp"],
      "targetDuration": 12
    },
    "videoPath": null,
    "uploadId": null,
    "tiktokUrl": null,
    "startedAt": "2026-04-15T00:00:00.000Z"
  },
  "completedJobs": [],
  "metrics": {
    "totalVideos": 0,
    "totalViews": 0,
    "totalLikes": 0,
    "avgEngagementRate": 0
  }
}
```

## Required Workflow

1. Read `pipeline-state.json` before handling any pipeline request.
2. If the file does not exist, create it with the schema above.
3. For "find trends" requests → Scout produces a trend brief and writes it to `trend-reports/`.
4. For "generate video" requests → Forge reads the latest trend brief, generates video, writes to `generated-videos/`.
5. For "upload to tiktok" requests → Nova reads the latest generated video, uploads via API, writes receipt to `upload-receipts/`.
6. After every step, update `pipeline-state.json` with current status.

## Environment Requirements

- **ComfyUI** must be accessible at `http://localhost:7820` for video frame generation.
- **FFmpeg** must be available on PATH for video assembly.
- **TikTok API** credentials must be configured via environment variables:
  - `TIKTOK_CLIENT_KEY`
  - `TIKTOK_CLIENT_SECRET`
  - `TIKTOK_ACCESS_TOKEN`
  - `TIKTOK_REFRESH_TOKEN`

## Response Style

- Report pipeline status after each action.
- Include estimated completion times for generation and upload steps.
- Share TikTok links and engagement metrics when available.
- If any step fails, report the error clearly and suggest recovery options.
