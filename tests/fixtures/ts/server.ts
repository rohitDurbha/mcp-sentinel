import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { ListToolsRequestSchema, Tool } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

const server = new McpServer({ name: "demo", version: "1.0.0" });
const BASE = "Read a file";
const READ_DESC = BASE + " from disk. " + `Handles "utf-8" text.`;

server.tool("echo", "Echoes back\tinput", { message: z.string().describe("Message to echo") }, async ({ message }) => ({
  content: [{ type: "text", text: message }],
}));

server.tool("no_desc", { a: z.number() }, async () => ({ content: [] }));

this.server.registerTool(
  "add",
  {
    title: "Add",
    description: ["Add two numbers.", "Returns the sum."].join("\n"),
    inputSchema: { a: z.number().describe("first"), b: z.number().optional().describe("second") },
  },
  async () => ({ content: [] }),
);

const READ_FILE_TOOL: Tool = {
  name: "read_file",
  description: READ_DESC,
  inputSchema: {
    type: "object",
    properties: { path: { type: "string", description: "Path to read" } },
  },
};

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    READ_FILE_TOOL,
    {
      name: "search",
      description: `Search ${SOMETHING} files`,
    },
  ],
}));

const pkg = { name: "not-a-tool", description: "package metadata" };
