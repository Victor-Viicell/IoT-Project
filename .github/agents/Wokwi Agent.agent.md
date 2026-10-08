---
name: Wokwi Agent
description: Describe what this custom agent does and when to use it.
argument-hint: The inputs this agent expects, e.g., "a task to implement" or "a question to answer".
# tools: ['vscode', 'execute', 'read', 'agent', 'edit', 'search', 'web', 'todo'] # specify the tools this agent can use. If not set, all enabled tools are allowed.
---

<!-- Tip: Use /create-agent in chat to generate content with agent assistance -->

---

Create an API token on the [Wokwi CI Dashboard](https://wokwi.com/dashboard/ci). Set the `WOKWI_CLI_TOKEN` environment variable to the token value.

If you haven't set up your project for Wokwi yet, you can use the `init` command to configure your project for Wokwi. Run the following command in your project's root directory:

```bash
wokwi-cli init
```

This command will ask you a few questions and will automatically generate [wokwi.toml](../vscode/project-config) and [diagram.json](../diagram-format) files for your project.

To run the simulation, use the following command:

```bash
wokwi-cli <your-project-directory>
```

The CLI will start the simulation and display the serial output. It will automatically exit after 30 seconds.

:::tip
A valid Wokwi CLI token starts with `wok_` and is exactly 44 characters long (including the `wok_` prefix). If you are
experiencing authorization issues, double check that your token is active, correctly formatted and doesn't contain any
spaces or fancy characters.
:::

## CLI Options

You can use the following options to customize the CLI behavior:

### Configuration

- `--elf <path>` - ELF file to simulate (default: read from wokwi.toml)
- `--diagram-file <path>` - Path to the diagram.json file, relative to project root (default: diagram.json)
- `--interactive` - Redirect stdin to the simulated serial port
- `--serial-log-file <path>` - Save the serial monitor output to the given file
- `--timeout <number>` - Timeout in simulation milliseconds (default: 30000)
- `--timeout-exit-code <number>` - Process exit code when timeout is reached (default: 42)

### Automation

- `--expect-text <string>` - Expect the given text in the output
- `--fail-text <string>` - Fail if the given text is found in the output
- `--scenario <path>` - Path to an [automation scenario](./automation-scenarios) file, relative to project root
- `--screenshot-part <string>` - Take a screenshot of the given part id (from diagram.json)
- `--screenshot-time <number>` - Time in simulation milliseconds to take the screenshot
- `--screenshot-file <string>` - File name to save the screenshot to (default: screenshot.png)
- `--vcd-file <path>` - Export [Logic Analyzer](../parts/wokwi-logic-analyzer) data to a VCD file

### General

- `--help`, `-h` - Prints help information and exit
- `--quiet`, `-q` - Quiet: do not print version or status messages


## Linting Diagrams

The `lint` command validates your [diagram.json](../diagram-format) file for errors and warnings before running a simulation:

```bash
wokwi-cli lint
```

The linter checks for common issues such as unknown part types, invalid pin connections, and missing components. By default, it fetches the latest board definitions from the Wokwi registry to ensure accurate validation.

---

The `idf-wokwi` Python package adds simulation support directly to Espressif's `idf.py` command. From `idf.py`, you can
run a simulation and pass a selection of options to customize its behavior.

Unlike `wokwi-cli`, you don't need to initalize a project as `idf-wokwi` will implicitly generate the relevant files
(`wokwi.toml`/`diagram.json`) by inferring information from ESP-IDF. You can however still add your own files if you
require other components.

## Getting Started

Create an API token on the [Wokwi CI Dashboard](https://wokwi.com/dashboard/ci). Set the `WOKWI_CLI_TOKEN` environment
variable to the token value.

Install the extension with the following command:
```bash
pip install idf-wokwi
```

You can now run a simulation by executing `idf.py wokwi`!

:::info
Module extensions to ``idf.py`` are only supported on ESP-IDF versions 6.0 or greater.
:::

## CLI Options

Pass any selection of the following commands to `idf.py wokwi` to customize its behavior during runtime.

- `--diagram-file` - Path to `diagram.json` (defaults to project root)
- `--timeout` - Simulation timeout in milliseconds (exit code 42 on timeout)
- `--expect-text` - Exit successfully when this text appears in serial output
- `--fail-text` - Exit with error when this text appears in serial output
- `--expect-regex` - Exit successfully when this regex matches a serial output line
- `--fail-regex` - Exit with error when this regex matches a serial output line

## Example Usage

```bash
export WOKWI_CI_TOKEN="your-token-here"

# Build and simulate
idf.py build
idf.py wokwi

# CI mode: exit when expected text appears
idf.py wokwi --timeout 10000 --expect-text "Hello world!"
```
