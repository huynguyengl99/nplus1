# Contributing to N Plus 1

Thank you for your interest in contributing to N Plus 1! This guide will help you set
up the development environment and understand the tools and processes used in this project.

## Prerequisites

Before starting development, ensure you have the following installed:


- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- 
- [uv](https://docs.astral.sh/uv/getting-started/installation/) for Python package management
- Python 3.10+ (project supports 3.10, 3.11, 3.12, and 3.13)

## Install the library for development

### Setting up your environment

Create your own virtual environment and activate it:

```bash
uv venv # or python -m venv .venv
source .venv/bin/activate
```

Then use uv to install all dev packages:
```bash
uv sync --all-extras
```

### Using tox for complete environment testing

For testing across multiple Python versions and configurations, we use tox:

```bash
# Install tox following the official documentation
# https://tox.wiki/en/latest/installation.html
uv tool install tox

# Run tests on all supported Python versions
tox

# Run tests for a specific environment
tox -e py310

# Run only the linting checks
tox -e lint

# Run test coverage
tox -e coverage
```


## Prepare the environment

Before running tests, ensure:
- Docker is running
- Run `docker compose up` to launch required services


## Code quality tools

N Plus 1 uses several tools to ensure code quality. You should run these tools before
submitting a pull request.

### Pre-commit hooks

We use pre-commit hooks to automatically check and format your code on commit. Install them with:

```bash
pip install pre-commit
pre-commit install
```

### Linting and formatting

For manual linting and formatting:

```bash
# Run linting checks
bash scripts/lint.sh

# Fix linting issues automatically
bash scripts/lint.sh --fix
```

This runs:
- [Ruff](https://github.com/astral-sh/ruff) for fast Python linting
- [Black](https://github.com/psf/black) for code formatting
- [toml-sort](https://github.com/pappasam/toml-sort) for TOML file formatting

### Type checking

We use multiple type checking tools for maximum safety:

```bash
# Run mypy on the nplusone package
bash scripts/mypy.sh

# Run pyright
pyright
```

The project uses strict type checking settings to ensure high code quality.

### Docstring coverage

We aim for high docstring coverage. Check your docstring coverage with:

```bash
# Run interrogate to check docstring coverage
interrogate -vv nplusone
```

The project requires at least 80% docstring coverage as configured in the project settings.

## Testing

### Running tests

```bash
# Run all tests
pytest tests

# Run tests with coverage report
pytest --cov-report term-missing --cov=nplusone tests
```

### Writing tests

When adding new features, please include appropriate tests in the `tests` directory. Tests should:

- Verify the expected behavior of your feature
- Include both success and failure cases
- Use the fixtures and utilities provided by the testing framework

## Validate your changes before submission

Before creating a pull request, please ensure your code meets the project's standards:

### 1. Run the test suite

```bash
pytest --cov-report term-missing --cov=nplusone tests
```

### 2. Run type checkers

```bash
bash scripts/mypy.sh
pyright
```

### 3. Lint and format your code

```bash
bash scripts/lint.sh --fix
```

### 4. Check docstring coverage

```bash
interrogate -vv nplusone
```

### 5. Run the complete validation suite with tox

```bash
tox
```

## Commit guidelines

For committing code, use the [Commitizen](https://commitizen-tools.github.io/commitizen/) tool to follow
commit best practices:

```bash
cz commit
```

This ensures that all commits follow the [Conventional Commits](https://www.conventionalcommits.org/) format.

## Creating a Pull Request

When creating a pull request:

1. Make sure all tests pass and code quality checks succeed
2. Update the documentation if needed
3. Add a clear description of your changes
4. Reference any related issues

## Development best practices

- **Keep changes focused**: Each PR should address a single concern
- **Write descriptive docstrings**: All public API functions should be well-documented
- **Add type annotations**: All code should be properly typed
- **Test thoroughly**: Include tests for all new functionality

These validation steps are also run automatically in the CI when you open the pull request.

Thank you for contributing to N Plus 1!
