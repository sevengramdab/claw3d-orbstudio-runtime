var fs = require("fs");
var b = fs.readFileSync("src/lib/skills/packaged.ts");
var cr = 0;
for (var i = 0; i < b.length; i++) { if (b[i] === 13) cr++; }
console.log("CR:", cr, "size:", b.length);

// Also check what test actually compares
var asset = fs.readFileSync("assets/skills/tiktok-video-pipeline/SKILL.md", "utf8");
console.log("Asset CR:", (asset.match(/\r/g) || []).length, "len:", asset.length);
