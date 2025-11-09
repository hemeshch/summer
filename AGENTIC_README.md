# Stella Agentic Features

Stella now includes powerful agentic capabilities that allow Claude to use tools to interact with the system, execute commands, read/write files, and more.

## What is Agentic Claude?

The `AgenticClaudeOutputBlock` is an enhanced version of the standard `ClaudeOutputBlock` that integrates with the agent infrastructure from `agent/stellagent_client`. This gives Claude access to:

- **File System Tools**: Read, write, list files and directories
- **Bash Tools**: Execute bash commands
- **Zsh Tools**: Execute zsh commands
- More tools can be easily added!

## How It Works

```
WebSocket Input
     ↓
TextMessageInput
     ↓
AgenticClaudeOutputBlock
     ├─→ Claude AI (processes message)
     ├─→ Tool Manager (executes tools)
     └─→ TextMessageOutput
     ↓
Output Handler (e.g., iMessage)
```

When you send a message to Claude, it can:
1. Analyze what needs to be done
2. Call appropriate tools (e.g., list files, run commands)
3. Process tool results
4. Generate a final response

All of this happens automatically in a single conversation turn.

## Quick Start

### 1. Basic Usage

```python
from io_system import AgenticClaudeOutputBlock

# Create agentic block with tools
block = AgenticClaudeOutputBlock(
    output_handler=my_handler,
    system_prompt="You are a helpful assistant.",
    enabled_tools=['file_system', 'bash']
)
```

### 2. With WebSocket → iMessage Pipeline

```python
from io_system import WebSocketTextInputProvider, AgenticClaudeOutputBlock
from io_system.handlers import create_imessage_handler

# Create pipeline
ws_provider = WebSocketTextInputProvider(url="wss://...")
imessage_handler = create_imessage_handler()

agentic_block = AgenticClaudeOutputBlock(
    output_handler=imessage_handler,
    enabled_tools=['file_system', 'bash']
)

ws_provider.connect_output_block(agentic_block)
ws_provider.start()
```

### 3. Run the Agentic Demo

```bash
# Make sure ANTHROPIC_API_KEY is set in .env
python main_agentic.py
```

This runs the full pipeline: WebSocket → Agentic Claude → iMessage

## Available Tools

### File System (`file_system`)

- `list_files`: List files in a directory
- `read_file`: Read file contents
- `write_file`: Write content to a file
- `create_directory`: Create a new directory
- And more...

### Bash (`bash`)

- `execute_command`: Execute bash commands
- Returns stdout, stderr, and exit code
- Full shell environment support

### Zsh (`zsh`)

- `execute_zsh_command`: Execute zsh commands
- Same features as bash tool

## Configuration

```python
AgenticClaudeOutputBlock(
    output_handler=handler,           # Function to handle outputs
    system_prompt="...",              # Custom system prompt
    model="claude-sonnet-4-5",        # Claude model to use
    max_tokens=4096,                  # Max tokens in response
    enabled_tools=['file_system'],    # List of tools to enable
    runtime_dir="./stella_runtime"    # Runtime directory for agent state
)
```

## Examples

### Example 1: File Operations

```python
from io_system import AgenticClaudeOutputBlock
from io_system.inputs import TextMessageInput

block = AgenticClaudeOutputBlock(
    enabled_tools=['file_system']
)

# Ask Claude to create a file
input_obj = TextMessageInput("Create a file called notes.txt with 'Hello World'")
block.process_input(input_obj)
# Claude will use the write_file tool automatically
```

### Example 2: System Commands

```python
block = AgenticClaudeOutputBlock(
    enabled_tools=['bash']
)

# Ask Claude to check disk usage
input_obj = TextMessageInput("What's the disk usage on this system?")
block.process_input(input_obj)
# Claude will use the bash tool to run 'df -h'
```

### Example 3: Combined Tools

```python
block = AgenticClaudeOutputBlock(
    enabled_tools=['file_system', 'bash']
)

# Complex task requiring multiple tools
input_obj = TextMessageInput(
    "Create a directory called 'logs', then create a file 'status.txt' "
    "with the output of the 'uptime' command"
)
block.process_input(input_obj)
# Claude will:
# 1. Use file_system to create directory
# 2. Use bash to run 'uptime'
# 3. Use file_system to write the result to a file
```

## Testing

### Run the Test Script

```bash
python test_agentic.py
```

This interactive test script demonstrates the agentic capabilities without requiring WebSocket or iMessage setup.

### Manual Testing

```python
from io_system import AgenticClaudeOutputBlock
from io_system.inputs import TextMessageInput

def print_response(output):
    print(f"Response: {output.text}")

block = AgenticClaudeOutputBlock(
    output_handler=print_response,
    enabled_tools=['file_system', 'bash']
)

# Send test message
input_obj = TextMessageInput("List files in the current directory")
block.process_input(input_obj)
```

## Architecture

### Components

1. **AgenticClaudeOutputBlock**: Main output block class
2. **ClaudeAgent**: Handles Claude API integration from agent infrastructure
3. **ToolManager**: Manages tool registration and execution
4. **Tool Providers**: Individual tools (FileSystemToolProvider, BashToolProvider, etc.)

### How Tools Work

1. Tools are registered with the ToolManager on initialization
2. When Claude wants to use a tool, it returns a tool_use block
3. The ClaudeAgent calls the tool via ToolManager
4. Tool results are sent back to Claude
5. Claude processes results and generates final response

### Conversation Flow

```
User: "Create a file called test.txt"
  ↓
Claude: [Decides to use write_file tool]
  ↓
ToolManager: [Executes write_file("test.txt", "")]
  ↓
Claude: [Receives success result]
  ↓
Claude: "I've created the file test.txt"
  ↓
Output Handler: [Sends response to user]
```

## Adding Custom Tools

You can add your own tools by creating a tool provider:

```python
from agent.stellagent_client.tool_system import BaseToolSetProvider, Tool, Parameter, ParameterType

class MyToolProvider(BaseToolSetProvider):
    def init(self):
        tools = [
            Tool(
                id="my_tool",
                name="My Tool",
                description="Does something cool",
                parameters={
                    "input": Parameter(
                        name="input",
                        type=ParameterType.STRING,
                        description="Input parameter",
                        required=True
                    )
                }
            )
        ]
        return tools, {}, {}  # tools, global_state, per_conversation_state

    def call_tool(self, tool_id, params, conv_state, global_state):
        if tool_id == "my_tool":
            result = f"You passed: {params['input']}"
            return result, None  # result, error
        return None, "Unknown tool"

# Register your tool
tool_manager.register_provider(MyToolProvider())
```

## Troubleshooting

### "ANTHROPIC_API_KEY must be set"

Make sure you have a `.env` file with:
```
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx
```

### "Failed to register tool"

Check that the agent directory is properly set up and tool providers are importable.

### Tool execution fails

- Check runtime directory permissions
- Verify bash/zsh is available on your system
- Check tool parameters match expected format

### High token usage

- Reduce `max_tokens` parameter
- Use fewer tools
- Clear conversation history periodically with `block.clear_history()`

## Performance Tips

1. **Enable only needed tools**: Don't enable all tools if you only need a few
2. **Use appropriate model**: claude-sonnet-4-5 is balanced, haiku is faster/cheaper
3. **Manage conversation history**: Long histories increase token usage
4. **Runtime directory**: Store on fast storage for better file I/O performance

## Security Considerations

⚠️ **Important**: The agentic system can execute commands and modify files on your system.

- Only enable tools you trust
- Be careful with bash/zsh tools - they can run arbitrary commands
- Consider running in a sandboxed environment for production use
- Review tool outputs before executing destructive actions
- Use appropriate file system permissions

## Next Steps

- Read the agent infrastructure docs in `agent/README.md`
- Explore available tools in `agent/stellagent_client/tools/`
- Create custom tools for your specific needs
- Integrate with other Stella pipelines

## License

Same as Stella - MIT
