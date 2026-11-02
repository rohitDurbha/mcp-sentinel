package main

import (
	"github.com/mark3labs/mcp-go/mcp"
	sdk "github.com/modelcontextprotocol/go-sdk/mcp"
)

const greetDesc = "Say hello " + `to someone`

func main() {
	tool := mcp.NewTool("hello_world",
		mcp.WithDescription(greetDesc),
		mcp.WithString("name", mcp.Required(), mcp.Description("Name of the person\nto greet")),
		mcp.WithNumber("times", mcp.Description("How many times")),
	)
	_ = tool

	sdk.AddTool(server, &sdk.Tool{Name: "greet", Description: "Greets the user"}, SayHi)
}
