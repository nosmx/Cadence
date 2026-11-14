// Downloads the small English Vosk speech model (~40 MB) into public/models/.
// The app restricts it to a few command words, so the small model is plenty.
import { createWriteStream, existsSync, mkdirSync, renameSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath } from 'node:url';

const FILE = 'vosk-model-small-en-us-0.15.tar.gz';
// Pre-packaged .tar.gz in the format vosk-browser expects (published by the vosk-browser project).
const URL = `https://ccoreilly.github.io/vosk-browser/models/${FILE}`;

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const dest = join(root, 'public', 'models', FILE);

if (existsSync(dest) && statSync(dest).size > 1_000_000) {
  console.log(`Model already present: ${dest}`);
  process.exit(0);
}

mkdirSync(dirname(dest), { recursive: true });
console.log(`Downloading ${URL}\n  -> ${dest}`);
try {
  const res = await fetch(URL);
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);
  const tmp = `${dest}.part`;
  await pipeline(Readable.fromWeb(res.body), createWriteStream(tmp));
  renameSync(tmp, dest);
  console.log(`Done (${(statSync(dest).size / 1e6).toFixed(1)} MB).`);
} catch (e) {
  console.error(`Download failed: ${e.message}`);
  console.error(`Download ${URL} manually and save it as ${dest}`);
  process.exit(1);
}
