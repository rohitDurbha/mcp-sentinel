package github

var ToolsetMetadataX = inventory.ToolsetMetadata{ID: "x", Description: "X tools"}

func GetThing(t translations.TranslationHelperFunc) inventory.ServerTool {
	return NewTool[In, Out](
		ToolsetMetadataX,
		mcp.Tool{
			Name:        "get_thing",
			Description: t("TOOL_GET_THING_DESCRIPTION", "Get a thing."),
			InputSchema: &jsonschema.Schema{
				Properties: map[string]*jsonschema.Schema{
					"owner": {Type: "string", Description: "The owner."},
				},
			},
		},
		handler,
	)
}

func dynamic(name string) {
	_ = mcp.NewTool(name, mcp.WithDescription("Dynamic name"))
}
