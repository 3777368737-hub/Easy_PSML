import { readFile } from "node:fs/promises";
import path from "node:path";

const root = path.resolve(import.meta.dirname, "..");
const pages = [
  "app/profile/page.tsx",
  "app/program/page.tsx",
  "app/story/page.tsx",
  "app/result/page.tsx",
  "app/batch/page.tsx",
];

const registrySource = await readFile(
  path.resolve(root, "../backend/app/services/agent_capabilities.py"),
  "utf8",
);
const registered = new Set(
  [...registrySource.matchAll(/"((?:profile|program|story|essay|project|result|history|batch|library|app|agent)\.[a-z_.]+)": CapabilitySpec/g)].map(
    (match) => match[1],
  ),
);

const missingAttributes = [];
const usedCapabilities = new Set();
for (const relativePath of pages) {
  const source = await readFile(path.resolve(root, relativePath), "utf8");
  for (const match of source.matchAll(/<button\b[\s\S]*?>/g)) {
    const tag = match[0];
    const capability = tag.match(/data-agent-capability="([^"]+)"/)?.[1];
    if (!capability) {
      const line = source.slice(0, match.index).split("\n").length;
      missingAttributes.push(`${relativePath}:${line}`);
      continue;
    }
    usedCapabilities.add(capability);
  }
}

if (missingAttributes.length) {
  console.error("Buttons without data-agent-capability:");
  missingAttributes.forEach((item) => console.error(`- ${item}`));
  process.exit(1);
}

const unknown = [...usedCapabilities].filter((name) => !registered.has(name));
if (unknown.length) {
  console.error("Unknown Agent capabilities:");
  unknown.forEach((name) => console.error(`- ${name}`));
  process.exit(1);
}

console.log(
  `Agent capability coverage OK: ${usedCapabilities.size} semantic page capabilities.`,
);
