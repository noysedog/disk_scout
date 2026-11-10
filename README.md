# Disk Scout

**A Linux disk usage analysis and cleanup assistant.**

Disk Scout is a Python-based utility designed to help Linux users understand how disk space is being used, identify storage bottlenecks, and safely reclaim unused space.

Instead of blindly deleting files, Disk Scout focuses on identifying what is consuming storage and providing the information needed to make informed cleanup decisions.

## Features

- **Disk usage analysis** – Inspect filesystem usage and available storage.
- **Large file discovery** – Identify files and directories consuming significant disk space.
- **Storage investigation** – Help locate unnecessary or forgotten data, including virtual machines, containers, and AI models.
- **Inode awareness** – Investigate inode consumption, not just disk capacity.
- **Safe cleanup approach** – Analysis is the primary operation; cleanup actions are separate and require explicit user confirmation.
- **Read-only by default** – Disk inspection does not modify or delete user data.

## Philosophy

Disk Scout follows a simple principle:

> Understand what is consuming disk space before deciding what to remove.

The tool is designed to prioritize transparency and user control. It does not assume that large files are unnecessary, nor does it automatically remove data just because it appears to be unused.

Personal files and important data should always remain under the user's control.

## Requirements

- Linux operating system
- Python 3.11 or later

The project uses Python's standard library for its runtime functionality.

## Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/disk_scout.git
cd disk_scout
```

### Using Conda

Create the development environment:

```bash
conda env create -f environment.yml
conda activate disk-scout
```

### Running Disk Scout

Display the available options:

```bash
python disk_scout.py --help
```

Follow the available command-line options to perform your disk analysis.

## Development and Testing

The project uses:

- **pytest** for automated testing.
- **flake8** for Python code linting.
- **GitHub Actions** for continuous integration.

Run the test suite:

```bash
pytest -v
```

Run lint checks:

```bash
flake8 .
```

## Safety

Disk Scout is intended to assist with system maintenance without compromising data integrity.

- No automatic deletion during analysis.
- Cleanup operations require explicit confirmation.
- No assumption that large files are disposable.
- User data protection takes priority over freeing disk space.

Always review cleanup suggestions before confirming any operation.

## Project Status

Disk Scout is under active development. Features, supported environments, and documentation may evolve over time.

## License

See the [LICENSE](LICENSE) file for licensing information.
