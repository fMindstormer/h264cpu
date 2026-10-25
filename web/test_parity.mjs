// node web/test_parity.mjs <program.json> <board.bin> <frames> <out prefix>
// Writes <prefix>.264 and <prefix>.mp4 with the browser writer; tests/test_web.py compares them with Python's.
// A program that ships its starting values (givenValues) takes "-" for the board.
import { readFileSync, writeFileSync } from "node:fs";
import { stream, mp4, concat, givenValues } from "./h264cpu.js";

const [progPath, boardPath, nFrames, prefix] = process.argv.slice(2);
const prog = JSON.parse(readFileSync(progPath));
let given;
if (prog.givenValues) given = givenValues(prog);
else {
  const cells = readFileSync(boardPath), plane = () => Int32Array.from(cells, (c) => c * 255);
  given = { S: [plane(), plane(), plane()], H: [plane(), plane(), plane()],
    K: [0, 1, 2].map(() => new Int32Array(prog.W * prog.H).fill(255)) };
}
const { frames, width, height } = stream(prog, given, +nFrames);
writeFileSync(`${prefix}.264`, concat(frames));
writeFileSync(`${prefix}.mp4`, mp4(frames, width, height, prog.fps));
