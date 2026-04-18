"use strict";

/**
 * ComfyUI-based short video generation.
 *
 * Pipeline: Generate N key frames via ComfyUI txt2img → assemble into MP4 via FFmpeg.
 * Falls back to a static frame slideshow if ComfyUI is offline.
 */

const fs = require("fs");
const path = require("path");
const http = require("http");
const { execFile } = require("child_process");

const COMFY_HOST = process.env.COMFY_HOST || "127.0.0.1";
const COMFY_PORT = parseInt(process.env.COMFY_PORT || "7820", 10);
const COMFY_BASE = `http://${COMFY_HOST}:${COMFY_PORT}`;
const CHECKPOINT = "v1-5-pruned-emaonly.safetensors";

function httpJson(method, urlString, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlString);
    const payload = body ? JSON.stringify(body) : null;
    const options = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname + url.search,
      method,
      headers: {
        "Content-Type": "application/json",
        ...(payload ? { "Content-Length": Buffer.byteLength(payload) } : {}),
      },
    };
    const req = http.request(options, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        const text = Buffer.concat(chunks).toString("utf8");
        try {
          resolve({ status: res.statusCode, data: JSON.parse(text) });
        } catch {
          resolve({ status: res.statusCode, data: text });
        }
      });
    });
    req.on("error", reject);
    req.setTimeout(5000, () => {
      req.destroy(new Error("ComfyUI connection timeout"));
    });
    if (payload) req.write(payload);
    req.end();
  });
}

function httpGetBuffer(urlString) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlString);
    const options = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname + url.search,
      method: "GET",
    };
    const req = http.request(options, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => resolve(Buffer.concat(chunks)));
    });
    req.on("error", reject);
    req.end();
  });
}

async function isComfyOnline() {
  try {
    const res = await httpJson("GET", `${COMFY_BASE}/system_stats`);
    return res.status === 200;
  } catch {
    return false;
  }
}

function buildTxt2ImgWorkflow(prompt, seed, width = 384, height = 384, steps = 8) {
  return {
    prompt: {
      "1": {
        class_type: "CheckpointLoaderSimple",
        inputs: { ckpt_name: CHECKPOINT },
      },
      "2": {
        class_type: "CLIPTextEncode",
        inputs: { text: prompt, clip: ["1", 1] },
      },
      "3": {
        class_type: "CLIPTextEncode",
        inputs: { text: "blurry, low quality, text, watermark", clip: ["1", 1] },
      },
      "4": {
        class_type: "EmptyLatentImage",
        inputs: { width, height, batch_size: 1 },
      },
      "5": {
        class_type: "KSampler",
        inputs: {
          model: ["1", 0],
          positive: ["2", 0],
          negative: ["3", 0],
          latent_image: ["4", 0],
          seed,
          steps,
          cfg: 5.5,
          sampler_name: "euler_ancestral",
          scheduler: "normal",
          denoise: 1.0,
        },
      },
      "6": {
        class_type: "VAEDecode",
        inputs: { samples: ["5", 0], vae: ["1", 2] },
      },
      "7": {
        class_type: "SaveImage",
        inputs: { images: ["6", 0], filename_prefix: "video_frame" },
      },
    },
  };
}

async function generateKeyFrame(prompt, seed, outputPath) {
  const workflow = buildTxt2ImgWorkflow(prompt, seed);
  const queueResult = await httpJson("POST", `${COMFY_BASE}/prompt`, workflow);
  if (!queueResult.data?.prompt_id) {
    throw new Error("ComfyUI prompt queue failed");
  }
  const promptId = queueResult.data.prompt_id;

  // Poll for completion
  for (let i = 0; i < 120; i++) {
    await new Promise((r) => setTimeout(r, 500));
    const histResult = await httpJson("GET", `${COMFY_BASE}/history/${promptId}`);
    const entry = histResult.data?.[promptId];
    if (!entry) continue;
    if (entry.status?.status_str === "error") {
      throw new Error("ComfyUI generation error");
    }
    const outputs = entry.outputs?.["7"]?.images;
    if (outputs && outputs.length > 0) {
      const img = outputs[0];
      const imgBuffer = await httpGetBuffer(
        `${COMFY_BASE}/view?filename=${encodeURIComponent(img.filename)}&subfolder=${encodeURIComponent(img.subfolder || "")}&type=${encodeURIComponent(img.type || "output")}`,
      );
      fs.writeFileSync(outputPath, imgBuffer);
      return outputPath;
    }
  }
  throw new Error("ComfyUI generation timed out");
}

function runFFmpeg(args) {
  return new Promise((resolve, reject) => {
    execFile("ffmpeg", args, { timeout: 60000 }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(`FFmpeg error: ${error.message}\n${stderr}`));
      } else {
        resolve(stdout);
      }
    });
  });
}

/**
 * Generate a short video from a text prompt.
 *
 * @param {object} options
 * @param {string} options.prompt - Visual style prompt for frame generation.
 * @param {number} [options.frameCount=8] - Number of key frames to generate.
 * @param {number} [options.durationSeconds=12] - Target video duration.
 * @param {string} options.outputDir - Directory for output files.
 * @param {string} [options.audioPath] - Optional audio overlay path.
 * @returns {Promise<{videoPath: string, thumbnailPath: string, durationMs: number, frameCount: number}>}
 */
async function generateShortVideo({
  prompt,
  frameCount = 8,
  durationSeconds = 12,
  outputDir,
  audioPath,
}) {
  const framesDir = path.join(outputDir, "frames");
  fs.mkdirSync(framesDir, { recursive: true });

  const baseSeed = Math.floor(Math.random() * 2147483647);
  const framePaths = [];
  const online = await isComfyOnline();

  if (online) {
    for (let i = 0; i < frameCount; i++) {
      const framePath = path.join(framesDir, `frame_${String(i).padStart(4, "0")}.png`);
      const framePrompt = `${prompt}, scene variation ${i + 1} of ${frameCount}, smooth transition`;
      await generateKeyFrame(framePrompt, baseSeed + i, framePath);
      framePaths.push(framePath);
    }
  } else {
    // Fallback: create placeholder gradient frames
    console.warn("[comfyui-video] ComfyUI offline — generating placeholder frames");
    for (let i = 0; i < frameCount; i++) {
      const framePath = path.join(framesDir, `frame_${String(i).padStart(4, "0")}.png`);
      // Use FFmpeg to generate a colored frame
      const hue = Math.floor((i / frameCount) * 360);
      await runFFmpeg([
        "-y",
        "-f", "lavfi",
        "-i", `color=c=0x${hueToHex(hue)}:s=1080x1080:d=0.04`,
        "-frames:v", "1",
        framePath,
      ]);
      framePaths.push(framePath);
    }
  }

  // Copy first frame as thumbnail
  const thumbnailPath = path.join(outputDir, "thumbnail.png");
  fs.copyFileSync(framePaths[0], thumbnailPath);

  // Assemble frames into video with Ken Burns + crossfade
  const frameDuration = durationSeconds / frameCount;
  const videoPath = path.join(outputDir, "output.mp4");

  // Build FFmpeg filter for Ken Burns (slow zoom) + crossfade transitions
  const inputs = framePaths.flatMap((p) => ["-loop", "1", "-t", String(frameDuration), "-i", p]);
  const filterParts = [];
  for (let i = 0; i < frameCount; i++) {
    const zoomStart = 1.0 + (i % 2 === 0 ? 0 : 0.04);
    const zoomEnd = 1.0 + (i % 2 === 0 ? 0.04 : 0);
    filterParts.push(
      `[${i}:v]scale=1080:1080,zoompan=z='${zoomStart}+(${zoomEnd}-${zoomStart})*on/(${Math.round(frameDuration * 30)})':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=${Math.round(frameDuration * 30)}:s=1080x1080:fps=30[v${i}]`,
    );
  }

  // Concatenate with crossfade
  let chain = `[v0]`;
  for (let i = 1; i < frameCount; i++) {
    const prev = i === 1 ? chain : `[xf${i - 1}]`;
    filterParts.push(`${prev}[v${i}]xfade=transition=fade:duration=0.5:offset=${(i * frameDuration) - 0.5}[xf${i}]`);
    chain = `[xf${i}]`;
  }
  filterParts.push(`${chain}format=yuv420p[outv]`);

  const ffmpegArgs = [
    "-y",
    ...inputs,
    "-filter_complex", filterParts.join(";"),
    "-map", "[outv]",
    "-c:v", "libx264",
    "-preset", "fast",
    "-crf", "23",
    "-movflags", "+faststart",
  ];

  // Add audio if provided
  if (audioPath && fs.existsSync(audioPath)) {
    ffmpegArgs.push("-i", audioPath, "-map", `${frameCount}:a`, "-c:a", "aac", "-shortest");
  }

  ffmpegArgs.push(videoPath);

  await runFFmpeg(ffmpegArgs);

  return {
    videoPath,
    thumbnailPath,
    durationMs: durationSeconds * 1000,
    frameCount,
  };
}

function hueToHex(hue) {
  // Simple HSL→hex for placeholder frames (S=100%, L=50%)
  const h = hue / 60;
  const x = Math.round(255 * (1 - Math.abs(h % 2 - 1)));
  let r = 0, g = 0, b = 0;
  if (h < 1) { r = 255; g = x; }
  else if (h < 2) { r = x; g = 255; }
  else if (h < 3) { g = 255; b = x; }
  else if (h < 4) { g = x; b = 255; }
  else if (h < 5) { r = x; b = 255; }
  else { r = 255; b = x; }
  return [r, g, b].map((v) => v.toString(16).padStart(2, "0")).join("");
}

module.exports = {
  generateShortVideo,
  generateKeyFrame,
  isComfyOnline,
};
