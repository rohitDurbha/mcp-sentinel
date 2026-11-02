package tools

var ListThings = mcpgrafana.MustTool(
	"list_things",
	`List things.
Second line.`,
	listThings,
	mcp.WithTitleAnnotation("List"),
)

var Other = NewToolResultText("not a tool")
