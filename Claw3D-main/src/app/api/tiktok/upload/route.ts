import { NextRequest, NextResponse } from "next/server";
import path from "path";
import fs from "fs";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { videoPath, title, description, hashtags } = body as {
      videoPath?: string;
      title?: string;
      description?: string;
      hashtags?: string[];
    };

    if (!videoPath || typeof videoPath !== "string") {
      return NextResponse.json(
        { error: "videoPath is required" },
        { status: 400 },
      );
    }

    // Resolve the video path relative to the project root
    const resolved = path.resolve(videoPath);
    if (!fs.existsSync(resolved)) {
      return NextResponse.json(
        { error: `Video file not found: ${resolved}` },
        { status: 404 },
      );
    }

    // Validate file extension
    const ext = path.extname(resolved).toLowerCase();
    if (ext !== ".mp4" && ext !== ".webm" && ext !== ".mov") {
      return NextResponse.json(
        { error: "Unsupported video format. Use .mp4, .webm, or .mov" },
        { status: 400 },
      );
    }

    // Check for TikTok credentials
    if (!process.env.TIKTOK_CLIENT_KEY || !process.env.TIKTOK_ACCESS_TOKEN) {
      return NextResponse.json(
        {
          error: "TikTok API credentials not configured. Set TIKTOK_CLIENT_KEY and TIKTOK_ACCESS_TOKEN environment variables.",
        },
        { status: 503 },
      );
    }

    // Dynamic import of the TikTok API module (CommonJS)
    const tiktokApi = require("../../../../server/tiktok-api");

    const fullTitle = [
      title || "AI Generated Video",
      ...(hashtags || []).map((tag: string) =>
        tag.startsWith("#") ? tag : `#${tag}`,
      ),
    ]
      .join(" ")
      .slice(0, 150);

    const { publishId } = await tiktokApi.publishVideo({
      videoPath: resolved,
      title: fullTitle,
      privacyLevel: "PUBLIC_TO_EVERYONE",
    });

    // Poll for initial status
    let statusResult = null;
    try {
      statusResult = await tiktokApi.checkPublishStatus({ publishId });
    } catch {
      // Status check can fail if video is still processing
    }

    return NextResponse.json({
      publishId,
      status: statusResult?.data?.status || "processing",
      shareUrl: statusResult?.data?.share_url || null,
      title: fullTitle,
    });
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Upload failed";
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
