# Nano Banana

A Claude Code skill for generating and editing images using the Gemini CLI's nanobanana extension.

## Setup notes for this repository

This skill has been installed into `.claude/skills/nano-banana/`. To use it, the
host environment needs the Gemini CLI, the nanobanana extension, and an API key.
The exact steps that were verified to work:

```bash
# 1. Install the CLI
npm install -g @google/gemini-cli

# 2. Provide your Gemini API key via environment variable.
#    The nanobanana extension reads NANOBANANA_API_KEY (this is the one that
#    actually matters). GEMINI_API_KEY is what SKILL.md's presence-check looks
#    for, so set both. Keep the value OUT of the repo — put it in your shell
#    profile or the environment's secret/env-var configuration, never a
#    committed file.
export NANOBANANA_API_KEY="your-api-key"
export GEMINI_API_KEY="your-api-key"

# 3. Install the extension non-interactively (the plain command prompts for
#    consent + settings and will hang in an automated shell).
gemini extensions install https://github.com/gemini-cli-extensions/nanobanana \
  --consent --skip-settings

# 4. (Optional) persist the key into the extension's own keychain-backed config:
gemini extensions config nanobanana "API Key"
```

Generated images are written to `./nanobanana-output/` in the current working
directory; that folder is git-ignored so images aren't committed.

## Features

- **Text-to-image generation** - Create images from natural language prompts
- **Image editing** - Modify existing images with instructions
- **Photo restoration** - Repair damaged or old photos
- **Icon generation** - Create app icons and favicons
- **Diagram creation** - Generate flowcharts and architecture diagrams
- **Pattern generation** - Create seamless textures and patterns
- **Story/sequential images** - Generate narrative image sequences

## Prerequisites

1. **Gemini CLI** - Install from [gemini-cli](https://github.com/google-gemini/gemini-cli)
2. **Gemini API Key** - Get one from [Google AI Studio](https://aistudio.google.com/)
3. **nanobanana extension** - Installed via Gemini CLI

## Installation

### 1. Install the Gemini CLI

```bash
npm install -g @google/gemini-cli
```

### 2. Set your API key

```bash
export NANOBANANA_GEMINI_API_KEY="your-api-key"
```

### 3. Install the nanobanana extension

```bash
gemini extensions install https://github.com/gemini-cli-extensions/nanobanana
```

### 4. Install this skill

Copy the `SKILL.md` file to your Claude Code skills directory:

```bash
mkdir -p ~/.claude/skills/nano-banana
cp SKILL.md ~/.claude/skills/nano-banana/
```

Or clone this repository directly:

```bash
git clone https://github.com/kkoppenhaver/cc-nano-banana ~/.claude/skills/nano-banana
```

## Usage

Once installed, Claude Code will automatically use this skill when you ask for image generation. Examples:

- "Generate a blog header image for a post about machine learning"
- "Create a YouTube thumbnail for a coding tutorial"
- "Make an app icon for a productivity tool"
- "Draw a flowchart showing user authentication"
- "Edit this image to remove the background"

## Available Commands

| Command | Description |
|---------|-------------|
| `/generate` | Text-to-image generation |
| `/edit` | Modify existing images |
| `/restore` | Repair damaged photos |
| `/icon` | Generate app icons |
| `/diagram` | Create flowcharts and diagrams |
| `/pattern` | Generate seamless patterns |
| `/story` | Create sequential/narrative images |
| `/nanobanana` | Natural language interface |

## Common Options

| Option | Description |
|--------|-------------|
| `--count=N` | Generate N variations (1-8) |
| `--preview` | Auto-open generated images |
| `--styles="style1,style2"` | Apply artistic styles |
| `--seed=N` | Seed for reproducible results |

## Output

Generated images are saved to `./nanobanana-output/` in your current working directory.

## Model Selection

Default model: `gemini-2.5-flash-image` (~$0.04/image)

For higher quality output:

```bash
export NANOBANANA_MODEL=gemini-3-pro-image-preview
```

## License

MIT

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
