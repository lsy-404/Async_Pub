import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const workspaceRoot = path.resolve(__dirname, "..");
const serverDir = path.join(workspaceRoot, "apps", "server");

const mode = process.argv[2];
const rawArgs = process.argv.slice(3);
const extraArgs = rawArgs[0] === "--" ? rawArgs.slice(1) : rawArgs;

/** @type {Record<string, string[]>} */
const modeToPythonArgs = {
  dev: ["-m", "uvicorn", "main:app", "--reload", "--port", "3001"],
  start: ["-m", "uvicorn", "main:app", "--port", "3001"],
  "test-google": ["test_google_speech.py"],
  "test-elevenlabs": ["test_elevenlabs.py"],
};

if (!modeToPythonArgs[mode]) {
  console.error(
    `[server-python] Unknown mode: ${mode}. Expected one of: ${Object.keys(modeToPythonArgs).join(", ")}`,
  );
  process.exit(1);
}

function commandExists(command) {
  const checker = process.platform === "win32" ? "where" : "which";
  const result = spawnSync(checker, [command], { stdio: "ignore" });
  return result.status === 0;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    stdio: "inherit",
    ...options,
  });

  if (result.error) {
    return { status: 1 };
  }

  return result;
}

const pythonArgs = [...modeToPythonArgs[mode], ...extraArgs];

if (commandExists("uv")) {
  const uvResult = run(
    "uv",
    ["run", "--directory", serverDir, "python", ...pythonArgs],
    {
      cwd: workspaceRoot,
    },
  );
  process.exit(uvResult.status ?? 1);
}

const explicitPythonPaths = [
  path.join(workspaceRoot, ".venv", "bin", "python"),
  path.join(workspaceRoot, ".venv", "Scripts", "python.exe"),
  path.join(serverDir, ".venv", "bin", "python"),
  path.join(serverDir, ".venv", "Scripts", "python.exe"),
].filter((candidatePath) => fs.existsSync(candidatePath));

for (const pythonPath of explicitPythonPaths) {
  const pythonResult = run(pythonPath, pythonArgs, { cwd: serverDir });
  if ((pythonResult.status ?? 1) === 0) {
    process.exit(0);
  }
}

const pythonCommandCandidates =
  process.platform === "win32" ? ["python", "py"] : ["python3", "python"];

for (const candidate of pythonCommandCandidates) {
  if (!commandExists(candidate)) {
    continue;
  }

  const pythonResult = run(candidate, pythonArgs, { cwd: serverDir });
  if ((pythonResult.status ?? 1) === 0) {
    process.exit(0);
  }
}

console.error(
  "[server-python] No usable Python runtime found. Install uv or python and retry.",
);
process.exit(1);
