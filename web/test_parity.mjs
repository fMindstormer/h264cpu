// node web/test_parity.mjs <program.json> <board.bin> <frames> <out prefix>
// Writes <prefix>.264 and <prefix>.mp4 with the browser writer; tests/test_web.py compares them with Python's.
import { readFileSync, writeFileSync } from "node:fs";
import { stream, mp4, concat } from "./h264cpu.js";

const [progPath, boardPath, nFrames, prefix] = process.argv.slice(2);
const prog = JSON.parse(readFileSync(progPath));
const N = prog.N, cells = readFileSync(boardPath);
const plane = () => Int32Array.from(cells, (c) => c * 255);
const given = { S: [plane(), plane(), plane()], H: [plane(), plane(), plane()],
  K: [0, 1, 2].map(() => new Int32Array(N * N).fill(255)) };
const { frames, width, height } = stream(prog, given, +nFrames);
writeFileSync(`${prefix}.264`, concat(frames));
writeFileSync(`${prefix}.mp4`, mp4(frames, width, height, prog.fps));
