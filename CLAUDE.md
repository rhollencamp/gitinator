This project uses the following languages / frameworks / libraries:
- Python 3.11.X
- Django 5.2.X

Use the Makefile for all common tasks: `make setup` to create the venv and install dependencies, `make lint` to lint, `make format` to format, and `make test` to run tests. Only activate the virtual environment manually (`source venv/bin/activate`) when running commands not covered by the Makefile.

Always add a module docstring to every Python file. Use discretion for method/function docstrings -- add them when the purpose or behavior isn't self-evident from the name and signature.

Place imports at the top of the file. Deferred (inline) imports are only acceptable when necessary to avoid circular imports or to defer a costly side-effect; in that case add a comment explaining why.
