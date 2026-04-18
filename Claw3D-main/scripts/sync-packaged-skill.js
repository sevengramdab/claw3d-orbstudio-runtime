"use strict";
const fs = require("fs");

// Read the actual SKILL.md from assets
const skillMd = fs.readFileSync("assets/skills/tiktok-video-pipeline/SKILL.md", "utf8");

// Read packaged.ts
let packaged = fs.readFileSync("src/lib/skills/packaged.ts", "utf8");

// Find the TIKTOK_VIDEO_PIPELINE_SKILL_MD constant
const marker = "const TIKTOK_VIDEO_PIPELINE_SKILL_MD = `";
const startIdx = packaged.indexOf(marker);
if (startIdx === -1) {
  console.error("Marker not found in packaged.ts");
  process.exit(1);
}

const contentStart = startIdx + marker.length;

// Find the closing unescaped backtick — scan for ` not preceded by \
let i = contentStart;
while (i < packaged.length) {
  const ch = packaged.charCodeAt(i);
  if (ch === 0x60) { // backtick
    // Check if preceded by backslash
    if (i > 0 && packaged.charCodeAt(i - 1) === 0x5c) {
      i++;
      continue;
    }
    break;
  }
  i++;
}
const contentEnd = i;
console.log("Found template content from", contentStart, "to", contentEnd, "(" + (contentEnd - contentStart) + " chars)");

// Escape backticks and dollar-braces for template literal safety
let escaped = "";
for (let j = 0; j < skillMd.length; j++) {
  const c = skillMd.charCodeAt(j);
  if (c === 0x60) { // backtick
    escaped += "\\`";
  } else if (c === 0x24 && j + 1 < skillMd.length && skillMd.charCodeAt(j + 1) === 0x7b) { // ${
    escaped += "\\${";
    j++; // skip the {
  } else {
    escaped += skillMd[j];
  }
}

// Replace content
const updated = packaged.substring(0, contentStart) + escaped + packaged.substring(contentEnd);
fs.writeFileSync("src/lib/skills/packaged.ts", updated, "utf8");

console.log("Synced TIKTOK_VIDEO_PIPELINE_SKILL_MD");
console.log("Asset length:", skillMd.length, "Escaped length:", escaped.length);

// Verify round-trip: eval the template literal and compare
const verify = escaped.replace(/\\`/g, "`").replace(/\\\$/g, "$");
if (verify === skillMd) {
  console.log("Round-trip verification: PASS");
} else {
  console.log("Round-trip verification: FAIL");
  for (let k = 0; k < Math.max(verify.length, skillMd.length); k++) {
    if (verify[k] !== skillMd[k]) {
      console.log("  First diff at index", k);
      console.log("  Verify:", JSON.stringify(verify.substring(k, k+30)));
      console.log("  Asset:", JSON.stringify(skillMd.substring(k, k+30)));
      break;
    }
  }
}
