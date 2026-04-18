"use strict";

/**
 * TikTok Content Posting API v2 client.
 *
 * Requires environment variables:
 *   TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET,
 *   TIKTOK_ACCESS_TOKEN, TIKTOK_REFRESH_TOKEN
 */

const fs = require("fs");
const path = require("path");
const https = require("https");

const API_BASE = "https://open.tiktokapis.com";

function getCredentials() {
  const clientKey = process.env.TIKTOK_CLIENT_KEY;
  const clientSecret = process.env.TIKTOK_CLIENT_SECRET;
  const accessToken = process.env.TIKTOK_ACCESS_TOKEN;
  const refreshToken = process.env.TIKTOK_REFRESH_TOKEN;
  if (!clientKey || !accessToken) {
    throw new Error(
      "TikTok credentials missing. Set TIKTOK_CLIENT_KEY and TIKTOK_ACCESS_TOKEN environment variables.",
    );
  }
  return { clientKey, clientSecret, accessToken, refreshToken };
}

function httpsJson(method, urlString, body, headers) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlString);
    const payload = body ? JSON.stringify(body) : null;
    const options = {
      hostname: url.hostname,
      port: 443,
      path: url.pathname + url.search,
      method,
      headers: {
        "Content-Type": "application/json; charset=UTF-8",
        ...(payload ? { "Content-Length": Buffer.byteLength(payload) } : {}),
        ...headers,
      },
    };
    const req = https.request(options, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        try {
          const text = Buffer.concat(chunks).toString("utf8");
          resolve({ status: res.statusCode, data: JSON.parse(text) });
        } catch (err) {
          reject(new Error(`TikTok API response parse error: ${err.message}`));
        }
      });
    });
    req.on("error", reject);
    if (payload) req.write(payload);
    req.end();
  });
}

/**
 * Initialize a direct video upload to TikTok.
 * Returns { publishId, uploadUrl } on success.
 */
async function initializeDirectPost({ title, videoPath, privacyLevel = "PUBLIC_TO_EVERYONE" }) {
  const { accessToken } = getCredentials();
  const stat = fs.statSync(videoPath);
  const fileSizeBytes = stat.size;

  const result = await httpsJson(
    "POST",
    `${API_BASE}/v2/post/publish/video/init/`,
    {
      post_info: {
        title: (title || "").slice(0, 150),
        privacy_level: privacyLevel,
        disable_duet: false,
        disable_comment: false,
        disable_stitch: false,
      },
      source_info: {
        source: "FILE_UPLOAD",
        video_size: fileSizeBytes,
        chunk_size: fileSizeBytes,
        total_chunk_count: 1,
      },
    },
    { Authorization: `Bearer ${accessToken}` },
  );

  if (!result.data?.data?.publish_id) {
    const errMsg = result.data?.error?.message || JSON.stringify(result.data);
    throw new Error(`TikTok init failed: ${errMsg}`);
  }

  return {
    publishId: result.data.data.publish_id,
    uploadUrl: result.data.data.upload_url,
  };
}

/**
 * Upload video binary to TikTok's upload URL.
 */
async function uploadVideoChunk({ uploadUrl, videoPath }) {
  const fileBuffer = fs.readFileSync(videoPath);
  const fileSize = fileBuffer.length;

  return new Promise((resolve, reject) => {
    const url = new URL(uploadUrl);
    const options = {
      hostname: url.hostname,
      port: 443,
      path: url.pathname + url.search,
      method: "PUT",
      headers: {
        "Content-Type": "video/mp4",
        "Content-Length": fileSize,
        "Content-Range": `bytes 0-${fileSize - 1}/${fileSize}`,
      },
    };
    const req = https.request(options, (res) => {
      const chunks = [];
      res.on("data", (chunk) => chunks.push(chunk));
      res.on("end", () => {
        resolve({ status: res.statusCode, ok: res.statusCode >= 200 && res.statusCode < 300 });
      });
    });
    req.on("error", reject);
    req.write(fileBuffer);
    req.end();
  });
}

/**
 * Check publish status of an uploaded video.
 */
async function checkPublishStatus({ publishId }) {
  const { accessToken } = getCredentials();
  const result = await httpsJson(
    "POST",
    `${API_BASE}/v2/post/publish/status/fetch/`,
    { publish_id: publishId },
    { Authorization: `Bearer ${accessToken}` },
  );
  return result.data;
}

/**
 * Refresh the access token using the refresh token.
 */
async function refreshAccessToken() {
  const { clientKey, clientSecret, refreshToken } = getCredentials();
  if (!clientSecret || !refreshToken) {
    throw new Error("Cannot refresh token: TIKTOK_CLIENT_SECRET and TIKTOK_REFRESH_TOKEN required.");
  }
  const result = await httpsJson(
    "POST",
    `${API_BASE}/v2/oauth/token/`,
    {
      client_key: clientKey,
      client_secret: clientSecret,
      grant_type: "refresh_token",
      refresh_token: refreshToken,
    },
    {},
  );
  if (!result.data?.access_token) {
    throw new Error(`Token refresh failed: ${JSON.stringify(result.data)}`);
  }
  return {
    accessToken: result.data.access_token,
    refreshToken: result.data.refresh_token,
    expiresIn: result.data.expires_in,
  };
}

/**
 * Full upload flow: init → upload chunk → return publish ID.
 */
async function publishVideo({ videoPath, title, privacyLevel }) {
  const { publishId, uploadUrl } = await initializeDirectPost({ title, videoPath, privacyLevel });
  await uploadVideoChunk({ uploadUrl, videoPath });
  return { publishId };
}

module.exports = {
  initializeDirectPost,
  uploadVideoChunk,
  checkPublishStatus,
  refreshAccessToken,
  publishVideo,
};
