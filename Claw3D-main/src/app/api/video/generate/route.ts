import { NextRequest, NextResponse } from "next/server";
import path from "path";
import fs from "fs";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { prompt, style, duration, outputName } = body as {
      prompt?: string;
      style?: string;
      duration?: number;
      outputName?: string;
    };

    if (!prompt || typeof prompt !== "string") {
      return NextResponse.json(
        { error: "prompt is required" },
        { status: 400 },
      );
    }

    const fullPrompt = style
      ? `${prompt}, ${style} style, cinematic, high quality`
      : `${prompt}, cinematic, high quality`;

    const durationSeconds = Math.min(Math.max(duration || 12, 3), 30);
    const slug = (outputName || prompt)
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .slice(0, 40);
    const outputDir = path.join(
      process.cwd(),
      "public",
      "generated-videos",
      `${slug}-${Date.now()}`,
    );
    fs.mkdirSync(outputDir, { recursive: true });

    // Dynamic import of the ComfyUI video module (CommonJS)
    const comfyVideo = require("../../../../server/comfyui-video");

    const result = await comfyVideo.generateShortVideo({
      prompt: fullPrompt,
      frameCount: Math.max(4, Math.round(durationSeconds / 1.5)),
      durationSeconds,
      outputDir,
    });

    // Make the video path relative to public/ for serving
    const publicRelative = path.relative(
      path.join(process.cwd(), "public"),
      result.videoPath,
    );
    const thumbnailRelative = path.relative(
      path.join(process.cwd(), "public"),
      result.thumbnailPath,
    );

    return NextResponse.json({
      videoPath: `/${publicRelative.replace(/\\/g, "/")}`,
      thumbnailPath: `/${thumbnailRelative.replace(/\\/g, "/")}`,
      durationMs: result.durationMs,
      frameCount: result.frameCount,
      outputDir,
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Video generation failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
