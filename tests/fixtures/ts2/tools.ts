export const databaseToolDefs = {
  list_tables: {
    description: "Lists all tables.",
    parameters: z.object({ schemas: z.array(z.string()).describe("Schemas to list") }).strict(),
    annotations: { title: "List tables" },
  },
};

const tools = [
  { name: "fetch_docs", description: "Fetch docs", paramsSchema: { q: z.string().describe("query") }, cb: async () => ({}) },
];

export class DbStatsTool extends MongoDBToolBase {
  static toolName = "db-stats";
  public description = "Returns statistics for a database";
}

class Helper {
  public description = "not a tool";
}

const schema = { type: "object", properties: { q: { description: "plain JSON schema property" } } };
